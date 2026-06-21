"""Photo template / frame API — CRUD, grid-slot helper, live preview,
per-event assignment."""

from __future__ import annotations

import asyncio
import json
import secrets
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlmodel import Session, select

from app.auth import require_role
from app.database import get_engine, get_session
from app.models import Event, OutputPreset, Photo, PhotoSession, Template
from app.services import collage_service

router = APIRouter(prefix="/api/v1/templates", tags=["templates"])


def _template_dict(t: Template) -> dict:
    d = t.model_dump()
    try:
        d["definition"] = json.loads(t.definition_json or "{}")
    except json.JSONDecodeError:
        d["definition"] = {"slots": [], "overlays": []}
    return d


def _sync_canvas_from_preset(t: Template, session: Session) -> None:
    """When a template is linked to a preset, its canvas follows the preset px."""
    if t.preset_id is None:
        return
    preset = session.get(OutputPreset, t.preset_id)
    if preset is not None:
        t.canvas_width = preset.width_px
        t.canvas_height = preset.height_px


@router.get("")
def list_templates(session: Session = Depends(get_session),
                   _user=Depends(require_role("admin", "organizer"))):
    return {"templates": [_template_dict(t) for t in session.exec(select(Template)).all()]}


@router.get("/fonts")
def list_fonts(_user=Depends(require_role("admin", "organizer"))):
    """Font labels available for text elements on this system."""
    return {"fonts": collage_service.available_fonts()}


@router.post("/grid-slots")
def grid_slots(body: dict, _user=Depends(require_role("admin", "organizer"))):
    """Generate evenly spaced slots for a rows×cols grid (editor helper)."""
    slots = collage_service.make_grid_slots(
        int(body.get("rows", 1)), int(body.get("cols", 1)),
        int(body.get("canvas_width", 1200)), int(body.get("canvas_height", 1800)),
        int(body.get("margin", 40)), int(body.get("gap", 20)),
    )
    return {"slots": slots}


@router.post("", status_code=201)
def create_template(body: dict, session: Session = Depends(get_session),
                    _user=Depends(require_role("admin", "organizer"))):
    definition = body.get("definition", {"slots": [], "overlays": []})
    slots = definition.get("slots", [])
    t = Template(
        name=body.get("name", "Neue Vorlage"),
        mode=body.get("mode", "grid"),
        canvas_width=int(body.get("canvas_width", 1200)),
        canvas_height=int(body.get("canvas_height", 1800)),
        photo_count=len(slots),
        preset_id=body.get("preset_id"),
        background_asset_id=body.get("background_asset_id"),
        overlay_asset_id=body.get("overlay_asset_id"),
        definition_json=json.dumps(definition),
    )
    _sync_canvas_from_preset(t, session)
    session.add(t)
    session.commit()
    session.refresh(t)
    return _template_dict(t)


@router.get("/{template_id:int}")
def get_template(template_id: int, session: Session = Depends(get_session),
                 _user=Depends(require_role("admin", "organizer"))):
    t = session.get(Template, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return _template_dict(t)


@router.put("/{template_id:int}")
def update_template(template_id: int, body: dict, session: Session = Depends(get_session),
                    _user=Depends(require_role("admin", "organizer"))):
    t = session.get(Template, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found")
    if "name" in body: t.name = body["name"]
    if "mode" in body: t.mode = body["mode"]
    if "canvas_width" in body: t.canvas_width = int(body["canvas_width"])
    if "canvas_height" in body: t.canvas_height = int(body["canvas_height"])
    if "preset_id" in body: t.preset_id = body["preset_id"]
    if "background_asset_id" in body: t.background_asset_id = body["background_asset_id"]
    if "overlay_asset_id" in body: t.overlay_asset_id = body["overlay_asset_id"]
    if "definition" in body:
        t.definition_json = json.dumps(body["definition"])
        t.photo_count = len(body["definition"].get("slots", []))
    # A linked preset's pixels win over any client-sent canvas size.
    _sync_canvas_from_preset(t, session)
    session.add(t)
    session.commit()
    session.refresh(t)
    return _template_dict(t)


@router.delete("/{template_id:int}", status_code=204)
def delete_template(template_id: int, session: Session = Depends(get_session),
                    _user=Depends(require_role("admin", "organizer"))):
    t = session.get(Template, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found")
    session.delete(t)
    session.commit()


@router.post("/preview")
async def preview_template(body: dict, request: Request,
                           _user=Depends(require_role("admin", "organizer"))):
    """Render a live preview of the (possibly unsaved) template and return JPEG.

    Uses the most recent real photos when ``use_photos`` is set, otherwise
    numbered placeholder tiles.
    """
    definition = body.get("definition", {"slots": [], "overlays": []})
    slots = definition.get("slots", [])
    template = {
        "canvas_width": int(body.get("canvas_width", 1200)),
        "canvas_height": int(body.get("canvas_height", 1800)),
        "background_asset_id": body.get("background_asset_id"),
        "overlay_asset_id": body.get("overlay_asset_id"),
        "definition_json": definition,
    }

    cfg = request.app.state.config
    storage = Path(cfg["photos"]["storage_path"])
    photo_paths: list[str] = []

    if body.get("use_photos"):
        engine = get_engine()
        with Session(engine) as session:
            recent = session.exec(
                select(Photo).order_by(Photo.captured_at.desc()).limit(len(slots))
            ).all()
        photo_paths = [str(storage / p.filename) for p in recent]

    def _render() -> bytes:
        tmp_dir = Path(tempfile.gettempdir())
        # If no real photos, drop numbered placeholders into a temp dir
        nonlocal photo_paths
        if not photo_paths:
            ph_paths = []
            for i, slot in enumerate(slots):
                img = collage_service.make_placeholder(i, slot.get("w", 100), slot.get("h", 100))
                p = tmp_dir / f"_tpl_ph_{i}.jpg"
                img.save(p, "JPEG", quality=85)
                ph_paths.append(str(p))
            photo_paths = ph_paths
        out = tmp_dir / "_tpl_preview.jpg"
        collage_service.render(template, photo_paths, out, jpeg_quality=80)
        return out.read_bytes()

    data = await asyncio.to_thread(_render)
    return Response(content=data, media_type="image/jpeg")


# ── Booth-facing (no auth) ───────────────────────────────────────────────

@router.get("/booth")
def booth_templates(session: Session = Depends(get_session)):
    """Templates offered at the booth for the active event (public).

    Returns the event's configured templates, or all templates if none set.
    """
    event = session.exec(select(Event).where(Event.is_active == True)).first()
    enabled_ids = []
    if event:
        try:
            enabled_ids = json.loads(event.config_json or "{}").get("template_ids", [])
        except json.JSONDecodeError:
            enabled_ids = []

    all_templates = session.exec(select(Template)).all()
    if enabled_ids:
        chosen = [t for t in all_templates if t.id in enabled_ids]
    else:
        chosen = all_templates
    return {"templates": [
        {"id": t.id, "name": t.name, "photo_count": t.photo_count,
         "canvas_width": t.canvas_width, "canvas_height": t.canvas_height}
        for t in chosen
    ]}


@router.post("/render")
async def render_collage(body: dict, request: Request,
                         session: Session = Depends(get_session)):
    """Render a template with captured photos into a new collage Photo (public).

    Body: {template_id, photo_ids: [...]}  (photo_ids in slot order)
    """
    template_id = body.get("template_id")
    photo_ids = body.get("photo_ids", [])
    t = session.get(Template, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found")

    cfg = request.app.state.config
    storage = Path(cfg["photos"]["storage_path"])

    photo_paths, session_id = [], None
    for pid in photo_ids:
        p = session.get(Photo, pid)
        if p:
            photo_paths.append(str(storage / p.filename))
            if session_id is None:
                session_id = p.session_id
    if session_id is None:
        active = session.exec(
            select(PhotoSession).where(PhotoSession.ended_at == None)
            .order_by(PhotoSession.started_at.desc())
        ).first()
        session_id = active.id if active else None
    if session_id is None:
        raise HTTPException(status_code=400, detail="Keine aktive Session für die Collage")

    now = datetime.utcnow()
    fname = f"collage_{now:%Y%m%d_%H%M%S}_{secrets.token_hex(3)}.jpg"
    out = storage / fname
    template = {
        "canvas_width": t.canvas_width, "canvas_height": t.canvas_height,
        "background_asset_id": t.background_asset_id,
        "overlay_asset_id": t.overlay_asset_id,
        "definition_json": json.loads(t.definition_json or "{}"),
    }
    quality = cfg.get("photos", {}).get("jpeg_quality", 90)
    await asyncio.to_thread(collage_service.render, template, photo_paths, out, quality)

    thumb_rel = await asyncio.to_thread(_make_collage_thumb, out, storage,
                                        tuple(cfg["photos"]["thumbnail_size"]))

    # A set/arrangement still gets an animated GIF — a slideshow of its shots.
    gif_filename = None
    if len(photo_paths) >= 2:
        gif_out = storage / f"{out.stem}_anim.gif"
        gif_path = await asyncio.to_thread(collage_service.render_set_gif, photo_paths, gif_out)
        if gif_path is not None:
            gif_filename = gif_path.name

    photo = Photo(
        session_id=session_id,
        filename=fname,
        thumbnail=thumb_rel,
        gif_filename=gif_filename,
        width=t.canvas_width, height=t.canvas_height,
        file_size=out.stat().st_size if out.exists() else None,
        captured_at=now,
        metadata_json=json.dumps({"collage": True, "template_id": template_id,
                                  "source_photo_ids": photo_ids}),
    )
    session.add(photo)
    session.commit()
    session.refresh(photo)

    await request.app.state.bus.emit("capture.completed", {
        "photo_id": photo.id, "filename": fname, "collage": True, "gif": gif_filename,
    })
    return {"id": photo.id, "filename": fname, "thumbnail": thumb_rel, "gif": gif_filename}


def _make_collage_thumb(src: Path, storage: Path, size: tuple) -> str | None:
    try:
        from PIL import Image
        thumb_dir = storage / "thumbs"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as img:
            img = img.convert("RGB")
            img.thumbnail(size)
            name = f"{src.stem}_thumb.jpg"
            img.save(thumb_dir / name, "JPEG", quality=75)
        return f"thumbs/{name}"
    except Exception:
        return None


# ── Per-event assignment (stored in Event.config_json) ───────────────────

@router.get("/event/{slug}")
def get_event_templates(slug: str, session: Session = Depends(get_session),
                        _user=Depends(require_role("admin", "organizer"))):
    event = session.exec(select(Event).where(Event.slug == slug)).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    try:
        cfg = json.loads(event.config_json or "{}")
    except json.JSONDecodeError:
        cfg = {}
    return {"template_ids": cfg.get("template_ids", [])}


@router.put("/event/{slug}")
def set_event_templates(slug: str, body: dict, session: Session = Depends(get_session),
                        _user=Depends(require_role("admin", "organizer"))):
    event = session.exec(select(Event).where(Event.slug == slug)).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    try:
        cfg = json.loads(event.config_json or "{}")
    except json.JSONDecodeError:
        cfg = {}
    cfg["template_ids"] = body.get("template_ids", [])
    event.config_json = json.dumps(cfg)
    session.add(event)
    session.commit()
    return {"template_ids": cfg["template_ids"]}
