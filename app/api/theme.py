"""Theme / appearance API — colours, sizes and a global background image.

Theme values are stored as DB settings (theme.*), so they persist across
restarts (applied by config.apply_db_settings at startup). GET is public because
the booth needs the theme too; writes are admin-only.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.auth import require_role
from app.config import get_config, set_nested
from app.database import get_session
from app.models import Setting

router = APIRouter(prefix="/api/v1/theme", tags=["theme"])

# Defaults match the :root variables in frontend/index.html (so the default
# theme renders identically to the shipped look).
THEME_DEFAULTS: dict = {
    "primary": "#6c8cff",
    "secondary": "#ff8a5b",
    "accent": "#2dd4bf",
    "background": "#0f1426",
    "surface": "#1a2138",
    "text": "#f1f4ff",
    "text_muted": "#97a3c4",
    "radius": 14,            # corner roundness (px)
    "ui_scale": 1.0,         # global UI size (root font-size multiplier)
    "heading_scale": 1.0,    # h1/h2 size multiplier
    "heading_font": "",      # CSS font-family for headings (empty = default)
    "background_image": "",  # URL to a global background image (empty = none)
    "background_dim": 0.0,   # 0..1 dark overlay over the background image
}

_ALLOWED_EXT = (".jpg", ".jpeg", ".png", ".webp")


def _theme_dir() -> Path:
    d = Path(get_config()["photos"]["storage_path"]).parent / "assets" / "theme"
    d.mkdir(parents=True, exist_ok=True)
    return d


def current_theme() -> dict:
    t = get_config().get("theme", {}) or {}
    return {k: t.get(k, dv) for k, dv in THEME_DEFAULTS.items()}


def _save_setting(session: Session, key: str, value) -> None:
    row = session.exec(select(Setting).where(Setting.key == key)).first()
    vj = json.dumps(value)
    if row:
        row.value_json = vj
        row.updated_at = datetime.utcnow()
    else:
        row = Setting(key=key, value_json=vj)
    session.add(row)


@router.get("")
def get_theme():
    """Current theme (public — used by the booth and admin)."""
    return current_theme()


@router.put("")
def put_theme(body: dict, session: Session = Depends(get_session),
             _admin=Depends(require_role("admin"))):
    """Persist theme values (only known keys are accepted)."""
    cfg = get_config()
    for k, v in (body or {}).items():
        if k in THEME_DEFAULTS:
            _save_setting(session, f"theme.{k}", v)
            set_nested(cfg, f"theme.{k}", v)
    session.commit()
    return current_theme()


@router.post("/reset")
def reset_theme(session: Session = Depends(get_session),
                _admin=Depends(require_role("admin"))):
    """Reset all theme values to the shipped defaults."""
    cfg = get_config()
    for k, v in THEME_DEFAULTS.items():
        _save_setting(session, f"theme.{k}", v)
        set_nested(cfg, f"theme.{k}", v)
    for old in _theme_dir().glob("background.*"):
        try:
            old.unlink()
        except OSError:
            pass
    session.commit()
    return current_theme()


@router.post("/background")
async def upload_background(file: UploadFile = File(...),
                           session: Session = Depends(get_session),
                           _admin=Depends(require_role("admin"))):
    """Upload a global background image."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Leere Datei")
    ext = (Path(file.filename or "").suffix or ".jpg").lower()
    if ext not in _ALLOWED_EXT:
        ext = ".jpg"
    for old in _theme_dir().glob("background.*"):
        try:
            old.unlink()
        except OSError:
            pass
    dest = _theme_dir() / f"background{ext}"
    dest.write_bytes(data)
    url = f"/api/v1/theme/background?v={int(dest.stat().st_mtime)}"  # cache-bust
    cfg = get_config()
    _save_setting(session, "theme.background_image", url)
    set_nested(cfg, "theme.background_image", url)
    session.commit()
    return {"status": "ok", "background_image": url}


@router.get("/background")
def get_background():
    """Serve the global background image (public)."""
    files = list(_theme_dir().glob("background.*"))
    if not files:
        raise HTTPException(status_code=404, detail="Kein Hintergrundbild")
    return FileResponse(str(files[0]))


@router.delete("/background")
def delete_background(session: Session = Depends(get_session),
                     _admin=Depends(require_role("admin"))):
    for old in _theme_dir().glob("background.*"):
        try:
            old.unlink()
        except OSError:
            pass
    cfg = get_config()
    _save_setting(session, "theme.background_image", "")
    set_nested(cfg, "theme.background_image", "")
    session.commit()
    return {"status": "ok"}
