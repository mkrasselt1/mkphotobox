"""Event management API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.auth import get_current_user, require_role
from app.database import get_session
from app.models import Event, User
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
