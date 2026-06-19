"""Authentication and authorization: JWT tokens + role-based permissions."""

from __future__ import annotations

from datetime import datetime, timedelta
from fnmatch import fnmatch
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlmodel import Session, select

from app.config import get_config
from app.database import get_session
from app.models import Permission, User

security = HTTPBearer(auto_error=False)

ALGORITHM = "HS256"


def _get_secret() -> str:
    cfg = get_config()
    secret = cfg["auth"]["secret_key"]
    if not secret:
        # Fallback for development — in production, must be set
        return "dev-secret-change-me-in-production"
    return secret


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_token(user_id: int, role: str) -> str:
    cfg = get_config()
    expire = datetime.utcnow() + timedelta(minutes=cfg["auth"]["token_expire_minutes"])
    payload = {"sub": str(user_id), "role": role, "exp": expire}
    return jwt.encode(payload, _get_secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _get_secret(), algorithms=[ALGORITHM])


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    session: Session = Depends(get_session),
) -> User:
    """FastAPI dependency: extract and validate the current user from JWT."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


_LOCAL_IPS = {"127.0.0.1", "::1", "localhost"}


def require_role(*roles: str):
    """FastAPI dependency factory: require one of the given roles, and — when
    `admin.local_only` is enabled — restrict to localhost + configured IPs."""

    async def _check(request: Request, user: User = Depends(get_current_user)):
        admin_cfg = get_config().get("admin", {})
        if admin_cfg.get("local_only"):
            client = request.client.host if request.client else ""
            allowed = _LOCAL_IPS | set(admin_cfg.get("allowed_ips", []) or [])
            if client not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admin-Zugriff nur lokal erlaubt (local_only aktiv)",
                )
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return _check


def check_permission(session: Session, user: User, setting_key: str, action: str = "read") -> bool:
    """Check if a user has permission to read/write a specific setting."""
    if user.role == "admin":
        return True
    if user.role == "user":
        return False

    # Organizer: check permission table
    perms = session.exec(select(Permission).where(Permission.user_id == user.id)).all()
    for perm in perms:
        if fnmatch(setting_key, perm.setting_key):
            if action == "read" and perm.can_read:
                return True
            if action == "write" and perm.can_write:
                return True
    return False


def ensure_default_admin(session: Session) -> None:
    """Create the default admin user if no admin exists."""
    existing = session.exec(select(User).where(User.role == "admin")).first()
    if existing is not None:
        return

    cfg = get_config()
    default_pw = cfg["auth"]["default_admin_password"]
    admin = User(
        username="admin",
        password_hash=hash_password(default_pw),
        role="admin",
    )
    session.add(admin)
    session.commit()


# ── Mieter (renter / organizer) sections ─────────────────────────────────
# Admin areas a Mieter can be granted. Sensitive areas (modules, triggers,
# payment, settings, users, system/shutdown, tests, network) are admin-only.
MIETER_SECTIONS: dict[str, str] = {
    "dashboard": "Dashboard",
    "events": "Veranstaltungen",
    "templates": "Foto-Vorlagen",
    "assets": "Vorlagen-Assets",
    "background": "Hintergrund",
    "cameras": "Kameras",
    "printer": "Drucker",
    "cd-burn": "CD/DVD brennen",
    "usb-export": "Auf USB kopieren",
    "wifi": "WLAN",
}

_SECTION_PREFIX = "section:"

# URL prefix -> section key, for central enforcement of organizer access.
SECTION_URL_PREFIXES: dict[str, str] = {
    "/api/v1/events": "events",
    "/api/v1/templates": "templates",
    "/api/v1/assets": "assets",
    "/api/v1/background": "background",
    "/api/v1/camera": "cameras",
    "/api/v1/printer": "printer",
    "/api/v1/cd-burn": "cd-burn",
    "/api/v1/usb-export": "usb-export",
    "/api/v1/wifi": "wifi",
}


def ensure_default_mieter(session: Session) -> None:
    """Create the default 'mieter' (organizer) account if it doesn't exist."""
    existing = session.exec(select(User).where(User.username == "mieter")).first()
    if existing is not None:
        return
    cfg = get_config()
    default_pw = cfg.get("auth", {}).get("default_mieter_password", "mieter")
    session.add(User(
        username="mieter",
        password_hash=hash_password(default_pw),
        role="organizer",
    ))
    session.commit()


def organizer_section_keys(user_id: int) -> set[str]:
    """The section keys a given organizer user has been granted."""
    from app.database import get_engine

    with Session(get_engine()) as session:
        perms = session.exec(select(Permission).where(Permission.user_id == user_id)).all()
    return {p.setting_key[len(_SECTION_PREFIX):] for p in perms
            if p.setting_key.startswith(_SECTION_PREFIX)}


def allowed_sections(session: Session, user: User) -> list[str]:
    """Section keys the user may see: admin -> all, organizer -> granted, user -> none."""
    if user.role == "admin":
        return list(MIETER_SECTIONS.keys())
    if user.role == "organizer":
        granted = {p.setting_key[len(_SECTION_PREFIX):]
                   for p in session.exec(select(Permission).where(Permission.user_id == user.id)).all()
                   if p.setting_key.startswith(_SECTION_PREFIX)}
        # dashboard is always available to an organizer as a landing area
        granted.add("dashboard")
        return [k for k in MIETER_SECTIONS if k in granted]
    return []
