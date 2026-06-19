"""Authentication and authorization: JWT tokens + role-based permissions."""

from __future__ import annotations

from datetime import datetime, timedelta
from fnmatch import fnmatch
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
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


def require_role(*roles: str):
    """FastAPI dependency factory: require the user to have one of the given roles."""

    async def _check(user: User = Depends(get_current_user)):
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
