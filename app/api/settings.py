"""Settings API endpoints."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from app.auth import check_permission, get_current_user, require_role
from app.config import get_config, get_nested, set_nested
from app.database import get_session
from app.models import Setting, User
from app.schemas import SettingUpdate

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


@router.get("/")
def get_settings(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return all settings, filtered by user permissions."""
    cfg = get_config()

    if user.role == "admin":
        return cfg

    if user.role == "user":
        return {}

    # Organizer: filter by readable permissions
    from app.models import Permission

    perms = session.exec(select(Permission).where(Permission.user_id == user.id, Permission.can_read == True)).all()
    result = {}
    for perm in perms:
        value = get_nested(cfg, perm.setting_key)
        if value is not None:
            set_nested(result, perm.setting_key, value)
    return result


@router.get("/{key:path}")
def get_setting(
    key: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not check_permission(session, user, key, "read"):
        raise HTTPException(status_code=403, detail="Permission denied")

    # Check DB override first
    db_setting = session.exec(select(Setting).where(Setting.key == key)).first()
    if db_setting:
        return {"key": key, "value": json.loads(db_setting.value_json), "source": "database"}

    cfg = get_config()
    value = get_nested(cfg, key)
    if value is None:
        raise HTTPException(status_code=404, detail="Setting not found")
    return {"key": key, "value": value, "source": "config"}


@router.put("/{key:path}")
def update_setting(
    key: str,
    body: SettingUpdate,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not check_permission(session, user, key, "write"):
        raise HTTPException(status_code=403, detail="Permission denied")

    # Store in DB (highest priority layer)
    db_setting = session.exec(select(Setting).where(Setting.key == key)).first()
    if db_setting:
        db_setting.value_json = json.dumps(body.value)
        db_setting.updated_at = datetime.utcnow()
        db_setting.updated_by = user.id
    else:
        db_setting = Setting(
            key=key,
            value_json=json.dumps(body.value),
            updated_by=user.id,
        )
    session.add(db_setting)
    session.commit()

    # Also update in-memory config
    cfg = get_config()
    set_nested(cfg, key, body.value)

    return {"status": "ok", "key": key}
