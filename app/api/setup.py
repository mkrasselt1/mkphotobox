"""Setup wizard API endpoint."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.auth import hash_password
from app.config import get_config, save_user_config
from app.database import get_session
from app.models import Event, User
from app.schemas import SetupRequest

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])


@router.get("/status")
def setup_status():
    cfg = get_config()
    return {"completed": cfg.get("setup", {}).get("completed", False)}


@router.post("/complete")
def complete_setup(
    body: SetupRequest,
    session: Session = Depends(get_session),
):
    cfg = get_config()
    if cfg.get("setup", {}).get("completed", False):
        raise HTTPException(status_code=400, detail="Setup already completed")

    # Update admin password
    from sqlmodel import select

    admin = session.exec(select(User).where(User.username == "admin")).first()
    if admin:
        admin.password_hash = hash_password(body.admin_password)
        session.add(admin)
    else:
        admin = User(
            username="admin",
            password_hash=hash_password(body.admin_password),
            role="admin",
        )
        session.add(admin)

    # Flush to get admin.id before creating the event
    session.flush()

    # Deactivate any existing default event
    existing_events = session.exec(select(Event)).all()
    for ev in existing_events:
        ev.is_active = False
        session.add(ev)

    # Create first event if provided
    if body.event_name:
        slug = body.event_slug or body.event_name
        slug = re.sub(r"[^a-z0-9-]", "-", slug.lower().strip()).strip("-")
        event = Event(
            name=body.event_name,
            slug=slug,
            organizer_id=admin.id,
            is_active=True,
        )
        session.add(event)

    session.commit()

    # Save config overrides — disable all cameras except the chosen one
    all_cameras = ("gphoto2", "digicamcontrol", "webrtc", "opencv")
    cameras_cfg = {cam: {"enabled": cam == body.camera} for cam in all_cameras}

    overrides = {
        "setup": {"completed": True},
        "i18n": {"default_locale": body.language},
        "cameras": cameras_cfg,
    }
    save_user_config(overrides)

    # Reload config
    from app.config import load_config
    load_config(reload=True)

    return {"status": "ok", "message": "Setup complete"}
