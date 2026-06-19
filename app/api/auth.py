"""Auth API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.auth import (
    MIETER_SECTIONS,
    allowed_sections,
    create_token,
    get_current_user,
    hash_password,
    require_role,
    verify_password,
)
from app.database import get_session
from app.models import Permission, User
from app.schemas import (
    LoginRequest,
    LoginResponse,
    PermissionResponse,
    PermissionSet,
    UserCreate,
    UserResponse,
    UserUpdate,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.username == body.username)).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    token = create_token(user.id, user.role)
    return LoginResponse(token=token, role=user.role, username=user.username)


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)):
    return user


@router.get("/my-sections")
def my_sections(session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    """Admin sections the current user may access (drives nav + routing)."""
    return {"role": user.role, "sections": allowed_sections(session, user)}


# ── Mieter (renter) rights management — admin only ───────────────────────

def _mieter_user(session: Session) -> User:
    user = session.exec(select(User).where(User.username == "mieter")).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Mieter-Konto nicht gefunden")
    return user


@router.get("/mieter-sections")
def get_mieter_sections(session: Session = Depends(get_session),
                        _admin: User = Depends(require_role("admin"))):
    """All assignable sections + which ones the Mieter currently has."""
    mieter = _mieter_user(session)
    granted = {p.setting_key[len("section:"):]
               for p in session.exec(select(Permission).where(Permission.user_id == mieter.id)).all()
               if p.setting_key.startswith("section:")}
    return {
        "all": [{"key": k, "label": v} for k, v in MIETER_SECTIONS.items()],
        "granted": [k for k in MIETER_SECTIONS if k in granted],
    }


@router.put("/mieter-sections")
def set_mieter_sections(body: dict, session: Session = Depends(get_session),
                        _admin: User = Depends(require_role("admin"))):
    """Replace the Mieter's granted sections. Body: {sections: [keys]}."""
    mieter = _mieter_user(session)
    keys = [k for k in (body.get("sections") or []) if k in MIETER_SECTIONS]
    # clear existing section perms, keep any non-section permissions intact
    for p in session.exec(select(Permission).where(Permission.user_id == mieter.id)).all():
        if p.setting_key.startswith("section:"):
            session.delete(p)
    for k in keys:
        session.add(Permission(user_id=mieter.id, setting_key=f"section:{k}",
                               can_read=True, can_write=True))
    session.commit()
    return {"granted": keys}


# ── User management (admin only) ─────────────────────────────────────────

user_router = APIRouter(prefix="/api/v1/users", tags=["users"])


@user_router.get("/", response_model=list[UserResponse])
def list_users(
    session: Session = Depends(get_session),
    _admin: User = Depends(require_role("admin")),
):
    return session.exec(select(User)).all()


@user_router.post("/", response_model=UserResponse, status_code=201)
def create_user(
    body: UserCreate,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_role("admin")),
):
    existing = session.exec(select(User).where(User.username == body.username)).first()
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@user_router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    body: UserUpdate,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_role("admin")),
):
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if body.username is not None:
        user.username = body.username
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@user_router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_role("admin")),
):
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    session.delete(user)
    session.commit()


# ── Permissions ───────────────────────────────────────────────────────────

@user_router.get("/{user_id}/permissions", response_model=list[PermissionResponse])
def get_permissions(
    user_id: int,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_role("admin")),
):
    return session.exec(select(Permission).where(Permission.user_id == user_id)).all()


@user_router.put("/{user_id}/permissions")
def set_permissions(
    user_id: int,
    permissions: list[PermissionSet],
    session: Session = Depends(get_session),
    _admin: User = Depends(require_role("admin")),
):
    # Delete existing permissions
    existing = session.exec(select(Permission).where(Permission.user_id == user_id)).all()
    for perm in existing:
        session.delete(perm)

    # Insert new
    for p in permissions:
        session.add(Permission(user_id=user_id, setting_key=p.setting_key, can_read=p.can_read, can_write=p.can_write))
    session.commit()
    return {"status": "ok"}
