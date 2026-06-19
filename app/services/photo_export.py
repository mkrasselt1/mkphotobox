"""Shared helpers for exporting photos (CD/DVD burning, USB copy, …).

Builds the list of source files and the list of selectable sources (events).
Kept free of FastAPI so it can be reused by any export backend.
"""

from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, select

from app.config import get_config
from app.database import get_engine
from app.models import Event, Photo, PhotoSession


def list_event_sources() -> dict:
    """Events with photo counts plus the grand total, to pick what to export."""
    engine = get_engine()
    sources = []
    total = 0
    with Session(engine) as session:
        for ev in session.exec(select(Event)).all():
            count = len(session.exec(
                select(Photo.id)
                .join(PhotoSession, Photo.session_id == PhotoSession.id)
                .where(PhotoSession.event_id == ev.id)
            ).all())
            total += count
            sources.append({
                "event_id": ev.id,
                "name": ev.name,
                "slug": ev.slug,
                "photo_count": count,
                "is_active": ev.is_active,
            })
    return {"events": sources, "total_photos": total}


def gather_files(scope: str, event_id: int | None, include_gifs: bool) -> list[tuple[str, str]]:
    """Build a list of (absolute_source_path, archive_name) to export.

    Raises ValueError on invalid input (e.g. scope="event" without event_id).
    """
    cfg = get_config()
    storage = Path(cfg["photos"]["storage_path"])
    engine = get_engine()
    files: list[tuple[str, str]] = []
    seen: set[str] = set()

    with Session(engine) as session:
        query = select(Photo)
        if scope == "event":
            if event_id is None:
                raise ValueError("event_id erforderlich")
            query = (
                query.join(PhotoSession, Photo.session_id == PhotoSession.id)
                .where(PhotoSession.event_id == event_id)
            )
        photos = session.exec(query).all()

    for photo in photos:
        for name in (photo.filename, photo.gif_filename if include_gifs else None):
            if not name or name in seen:
                continue
            src = storage / name
            if src.exists():
                files.append((str(src.resolve()), name))
                seen.add(name)
    return files
