"""Configurable filename generation for photos and downloads."""

from __future__ import annotations

import secrets
from datetime import datetime


def build_filename(
    template: str,
    event_slug: str = "photo",
    seq: int = 0,
    extension: str = ".jpg",
    now: datetime | None = None,
) -> str:
    """Build a filename from a template with placeholders.

    Placeholders:
        {event}  - event slug
        {date}   - YYYYMMDD
        {time}   - HHMMSS
        {seq}    - sequence number (zero-padded 4 digits)
        {random} - 6 hex chars
    """
    if now is None:
        now = datetime.utcnow()

    result = template.format(
        event=_safe(event_slug),
        date=now.strftime("%Y%m%d"),
        time=now.strftime("%H%M%S"),
        seq=f"{seq:04d}",
        random=secrets.token_hex(3),
    )

    # Ensure no double dots or weird chars
    result = result.strip("_- .")
    if not result:
        result = f"photo_{now.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"

    return result + extension


def _safe(s: str) -> str:
    """Make a string filesystem-safe."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s).strip("_")
