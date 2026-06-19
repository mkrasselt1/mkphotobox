"""Event management API endpoints."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.auth import get_current_user, require_role
from app.config import get_config
from app.database import get_session
from app.models import (
    Collage, CollagePhoto, Event, OutputJob, Payment, Photo, PhotoSession,
    Template, User,
)
from app.schemas import EventCreate, EventResponse, EventUpdate

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.get("/", response_model=list[EventResponse])
def list_events(
    session: Session = Depends(get_session),
    user: User = Depends(require_role("admin", "organizer")),
):
    if user.role == "admin":
        return session.exec(select(Event)).all()
    return session.exec(select(Event).where(Event.organizer_id == user.id)).all()


@router.post("/", response_model=EventResponse, status_code=201)
def create_event(
    body: EventCreate,
    session: Session = Depends(get_session),
    user: User = Depends(require_role("admin", "organizer")),
):
    existing = session.exec(select(Event).where(Event.slug == body.slug)).first()
    if existing:
        raise HTTPException(status_code=409, detail="Event slug already exists")
    event = Event(
        name=body.name,
        slug=body.slug,
        organizer_id=user.id,
        config_json=body.config_json,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


@router.get("/active", response_model=EventResponse | None)
def get_active_event(session: Session = Depends(get_session)):
    """Get the currently active event (no auth required for booth)."""
    return session.exec(select(Event).where(Event.is_active == True)).first()


@router.get("/{slug}", response_model=EventResponse)
def get_event(slug: str, session: Session = Depends(get_session)):
    event = session.exec(select(Event).where(Event.slug == slug)).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.put("/{slug}", response_model=EventResponse)
def update_event(
    slug: str,
    body: EventUpdate,
    session: Session = Depends(get_session),
    user: User = Depends(require_role("admin", "organizer")),
):
    event = session.exec(select(Event).where(Event.slug == slug)).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if user.role == "organizer" and event.organizer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your event")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(event, field, value)
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


@router.post("/{slug}/activate", response_model=EventResponse)
def activate_event(
    slug: str,
    session: Session = Depends(get_session),
    _user: User = Depends(require_role("admin", "organizer")),
):
    # Deactivate all other events
    all_events = session.exec(select(Event)).all()
    for ev in all_events:
        ev.is_active = False
        session.add(ev)

    event = session.exec(select(Event).where(Event.slug == slug)).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    event.is_active = True
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


@router.delete("/{slug}")
def delete_event(
    slug: str,
    body: dict | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(require_role("admin", "organizer")),
):
    """Delete an event. ``body`` flags control what else is removed:
    {photos, gifs, templates, assets} (all bool). The event row, its sessions
    and photo records are always removed (DB integrity); the flags control the
    on-disk files and shared design resources."""
    event = session.exec(select(Event).where(Event.slug == slug)).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if user.role == "organizer" and event.organizer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your event")

    body = body or {}
    del_photos = bool(body.get("photos", True))
    del_gifs = bool(body.get("gifs", True))
    del_templates = bool(body.get("templates", False))
    del_assets = bool(body.get("assets", False))

    storage = Path(get_config()["photos"]["storage_path"])
    removed = {"photos": 0, "gifs": 0, "templates": 0, "assets": 0}

    def _unlink(rel):
        if rel:
            try:
                (storage / rel).unlink(missing_ok=True)
            except OSError:
                pass

    # ── gather sessions / photos / collages ───────────────────────────────
    sessions = session.exec(select(PhotoSession).where(PhotoSession.event_id == event.id)).all()
    sess_ids = [s.id for s in sessions]
    photos = session.exec(select(Photo).where(Photo.session_id.in_(sess_ids))).all() if sess_ids else []
    photo_ids = [p.id for p in photos]
    collages = session.exec(select(Collage).where(Collage.session_id.in_(sess_ids))).all() if sess_ids else []
    collage_ids = [c.id for c in collages]

    # ── delete files per flags ────────────────────────────────────────────
    for p in photos:
        if del_photos:
            _unlink(p.filename)
            _unlink(p.thumbnail)
            removed["photos"] += 1
        if del_gifs and p.gif_filename:
            _unlink(p.gif_filename)
            removed["gifs"] += 1
    if del_photos:
        for c in collages:
            _unlink(c.result_path)

    # ── delete dependent rows (FK-safe order) ─────────────────────────────
    if photo_ids:
        for oj in session.exec(select(OutputJob).where(OutputJob.photo_id.in_(photo_ids))).all():
            session.delete(oj)
        for cp in session.exec(select(CollagePhoto).where(CollagePhoto.photo_id.in_(photo_ids))).all():
            session.delete(cp)
    if collage_ids:
        for oj in session.exec(select(OutputJob).where(OutputJob.collage_id.in_(collage_ids))).all():
            session.delete(oj)
        for cp in session.exec(select(CollagePhoto).where(CollagePhoto.collage_id.in_(collage_ids))).all():
            session.delete(cp)
    for c in collages:
        session.delete(c)
    for p in photos:
        session.delete(p)
    for s in sessions:
        session.delete(s)
    for pay in session.exec(select(Payment).where(Payment.event_id == event.id)).all():
        session.delete(pay)

    # ── templates assigned to this event ──────────────────────────────────
    try:
        template_ids = json.loads(event.config_json or "{}").get("template_ids", [])
    except json.JSONDecodeError:
        template_ids = []

    candidate_asset_ids: set[int] = set()
    if del_templates or del_assets:
        for tid in template_ids:
            t = session.get(Template, tid)
            if t is None:
                continue
            for a in (t.background_asset_id, t.overlay_asset_id):
                if a:
                    candidate_asset_ids.add(a)
            try:
                for ov in json.loads(t.definition_json or "{}").get("overlays", []):
                    if ov.get("asset_id"):
                        candidate_asset_ids.add(ov["asset_id"])
            except json.JSONDecodeError:
                pass
            if del_templates:
                session.delete(t)
                removed["templates"] += 1

    session.delete(event)
    session.commit()  # commit before touching assets so FK refs are gone

    # ── assets: only delete those no longer used by any remaining template ─
    if del_assets and candidate_asset_ids:
        from app.services import asset_service
        remaining = session.exec(select(Template)).all()
        still_used: set[int] = set()
        for t in remaining:
            for a in (t.background_asset_id, t.overlay_asset_id):
                if a:
                    still_used.add(a)
            try:
                for ov in json.loads(t.definition_json or "{}").get("overlays", []):
                    if ov.get("asset_id"):
                        still_used.add(ov["asset_id"])
            except json.JSONDecodeError:
                pass
        for aid in candidate_asset_ids - still_used:
            if asset_service.delete_asset(aid):
                removed["assets"] += 1

    return {"status": "deleted", "event": slug, "removed": removed}
