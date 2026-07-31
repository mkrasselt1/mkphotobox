"""Photo capture and management API endpoints."""

from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from sqlmodel import Session, select

from app.auth import get_current_user, require_role
from app.database import get_session
from app.models import Event, OutputJob, Photo, PhotoSession
from app.schemas import PhotoResponse, SessionResponse

router = APIRouter(prefix="/api/v1", tags=["photos"])


def _get_photo_dir(cfg: dict) -> Path:
    path = Path(cfg["photos"]["storage_path"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get_thumb_dir(cfg: dict) -> Path:
    path = Path(cfg["photos"]["storage_path"]) / "thumbs"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ── Sessions ──────────────────────────────────────────────────────────────

@router.post("/sessions/start", response_model=SessionResponse)
def start_session(session: Session = Depends(get_session)):
    """Start a new photo session for the active event."""
    event = session.exec(select(Event).where(Event.is_active == True)).first()
    if event is None:
        event = Event(name="Photobox", slug="default", is_active=True)
        session.add(event)
        session.commit()
        session.refresh(event)

    token = secrets.token_urlsafe(8)
    photo_session = PhotoSession(event_id=event.id, token=token)
    session.add(photo_session)
    session.commit()
    session.refresh(photo_session)
    return photo_session


@router.get("/sessions/{token}", response_model=SessionResponse)
def get_session_info(token: str, session: Session = Depends(get_session)):
    ps = session.exec(select(PhotoSession).where(PhotoSession.token == token)).first()
    if ps is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return ps


@router.post("/sessions/{token}/end", response_model=SessionResponse)
def end_session(token: str, session: Session = Depends(get_session)):
    ps = session.exec(select(PhotoSession).where(PhotoSession.token == token)).first()
    if ps is None:
        raise HTTPException(status_code=404, detail="Session not found")
    ps.ended_at = datetime.utcnow()
    session.add(ps)
    session.commit()
    session.refresh(ps)
    return ps


# ── Looks / Filter ────────────────────────────────────────────────────────

@router.get("/photos/filters")
def list_photo_filters(request: Request):
    """Looks the booth may offer (public — the booth builds its chooser from this).

    The CSS string is what the booth puts on the live preview so guests see the
    look before posing; the server bakes the matching version into the photo."""
    from app.services import photo_filters

    cfg = request.app.state.config
    if not photo_filters.is_enabled(cfg):
        return {"enabled": False, "filters": []}
    return {"enabled": True, "filters": photo_filters.available(cfg)}


# ── Capture ───────────────────────────────────────────────────────────────

@router.post("/photos/capture", response_model=PhotoResponse)
async def capture_photo(request: Request, body: dict = Body(default={}),
                        session: Session = Depends(get_session)):
    """Trigger a photo capture using the active camera.

    ``part_of_set`` (from the booth) marks a raw shot of a multi-photo set —
    those are intermediate and not mirrored to the remote gallery individually
    (only the finished collage is).

    ``filter`` is the look the guest picked (see /photos/filters); it is baked
    into the stored photo so it survives into collage, print and download."""
    part_of_set = bool((body or {}).get("part_of_set"))
    filter_id = (body or {}).get("filter") or None
    app = request.app
    cfg = app.state.config
    cameras = app.state.cameras
    bus = app.state.bus

    # Get or create an active event
    event = session.exec(select(Event).where(Event.is_active == True)).first()
    if event is None:
        # Auto-create a default event so the booth works out of the box
        event = Event(name="Photobox", slug="default", is_active=True)
        session.add(event)
        session.commit()
        session.refresh(event)

    # Find active session or create one
    active_session = session.exec(
        select(PhotoSession)
        .where(PhotoSession.event_id == event.id, PhotoSession.ended_at == None)
        .order_by(PhotoSession.started_at.desc())
    ).first()
    if active_session is None:
        active_session = PhotoSession(event_id=event.id, token=secrets.token_urlsafe(8))
        session.add(active_session)
        session.commit()
        session.refresh(active_session)

    await bus.emit("capture.started", {"camera": cameras.active_id})

    try:
        jpeg_bytes = await cameras.capture()
    except Exception as e:
        await bus.emit("capture.error", {"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Capture failed: {e}")

    # Apply background removal to captured photo (AI mode runs here, not in the camera)
    cam = cameras.capture_camera or cameras.preview_camera
    if cam and hasattr(cam, "bg_remover"):
        bg = cam.bg_remover
        if bg.enabled:
            import cv2
            import numpy as np
            nparr = np.frombuffer(jpeg_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is not None:
                frame = await asyncio.to_thread(bg.apply_to_capture, frame)
                _, jpeg_out = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                jpeg_bytes = jpeg_out.tobytes()

    # Build filename from template
    from app.services.filename_service import build_filename
    now = datetime.utcnow()
    seq = session.exec(
        select(Photo).where(Photo.session_id == active_session.id)
    ).all()
    filename_template = cfg.get("photos", {}).get("filename_template", "{event}_{date}_{time}_{seq}")
    filename = build_filename(filename_template, event_slug=event.slug, seq=len(seq), now=now)

    # Bake in the look the guest chose, before the metadata is written (the
    # filter re-encodes, EXIF splicing afterwards does not).
    from app.services import photo_filters
    if filter_id and photo_filters.is_enabled(cfg):
        jpeg_bytes = await asyncio.to_thread(
            photo_filters.apply_to_jpeg, jpeg_bytes, filter_id,
            cfg.get("photos", {}).get("jpeg_quality", 92))

    # Save to disk
    photo_dir = _get_photo_dir(cfg)
    filepath = photo_dir / filename
    await asyncio.to_thread(filepath.write_bytes, jpeg_bytes)

    # Generate thumbnail
    thumb_path = await asyncio.to_thread(
        _generate_thumbnail, filepath, _get_thumb_dir(cfg), cfg["photos"]["thumbnail_size"]
    )

    # Create GIF from buffered preview frames
    gif_filename = None
    gif_service = getattr(app.state, "gif_service", None)
    if gif_service and gif_service.enabled:
        gif_base = filepath.stem
        gif_path = await gif_service.create_gif(photo_dir, gif_base)
        if gif_path:
            gif_filename = gif_path.name

    # Save to DB
    photo = Photo(
        session_id=active_session.id,
        filename=filename,
        gif_filename=gif_filename,
        thumbnail=f"thumbs/{filepath.stem}_thumb.jpg" if thumb_path else None,
        file_size=len(jpeg_bytes),
        captured_at=now,
        camera_module=cameras.active_id,
        metadata_json=json.dumps({"filter": filter_id}) if filter_id else "{}",
    )
    session.add(photo)
    session.commit()
    session.refresh(photo)

    await bus.emit("capture.completed", {
        "photo_id": photo.id, "filename": filename, "gif": gif_filename,
        "intermediate": part_of_set,
    })
    return photo


@router.post("/photos/upload")
async def upload_frame(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """Receive a captured frame from the browser (WebRTC camera)."""
    cameras = request.app.state.cameras
    cam = cameras.active_camera
    if cam is None:
        raise HTTPException(status_code=400, detail="No active camera")

    jpeg_bytes = await file.read()

    # If it's a WebRTC camera, store the frame
    if hasattr(cam, "receive_frame"):
        await cam.receive_frame(jpeg_bytes)

    return {"status": "ok"}


# ── Live Camera Stream ────────────────────────────────────────────────────

@router.get("/camera/stream")
async def camera_stream(request: Request):
    """MJPEG live stream from the active server-side camera.

    The browser can display this directly in an <img> tag:
        <img src="/api/v1/camera/stream">
    """
    cameras = request.app.state.cameras
    cam = cameras.active_camera
    if cam is None:
        raise HTTPException(status_code=503, detail="No active camera")

    async def generate():
        async for frame in cam.stream_preview():
            if not frame:
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame)).encode() + b"\r\n"
                b"\r\n" + frame + b"\r\n"
            )

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/camera/snapshot")
async def camera_snapshot(request: Request):
    """Single JPEG snapshot from the active camera preview."""
    cameras = request.app.state.cameras
    cam = cameras.active_camera
    if cam is None:
        raise HTTPException(status_code=503, detail="No active camera")

    frame = await cam.get_preview_frame()
    if not frame:
        raise HTTPException(status_code=503, detail="No frame available")
    from fastapi.responses import Response
    return Response(content=frame, media_type="image/jpeg")


@router.get("/camera/devices")
async def list_camera_devices(request: Request):
    """Discover available camera hardware with human-readable names.

    Devices currently in use by the server are marked as working without
    re-probing them (which would fail because the device is already open).
    """
    import asyncio
    from app.services.device_discovery import discover_cameras

    # Collect device indices currently held by the server
    cameras = request.app.state.cameras
    active_indices = set()
    for cam_id in [cameras.active_id, cameras.capture_id]:
        if cam_id and "opencv" in cam_id:
            # Extract index from "camera.opencv.1"
            parts = cam_id.split(".")
            if len(parts) >= 3 and parts[-1].isdigit():
                active_indices.add(int(parts[-1]))

    devices = await asyncio.to_thread(discover_cameras, skip_indices=active_indices)

    # Mark skipped (server-held) devices as working
    for d in devices:
        if d.index in active_indices:
            d.working = True
            if "[kein Signal]" in d.name:
                d.name = d.name.replace(" [kein Signal]", "")
            if "[aktiv]" not in d.name:
                d.name += " [aktiv]"

    return [{"index": d.index, "name": d.name, "device_id": d.device_id, "backend": d.backend, "working": d.working} for d in devices]


@router.get("/camera/status")
async def camera_status(request: Request):
    """Return info about active cameras."""
    cameras = request.app.state.cameras
    return {
        "preview": cameras.active_id,
        "capture": cameras.capture_id or cameras.active_id,
        "active": cameras.active_id,  # backward compat
        "cameras": cameras.list_cameras(),
        "mode": "webrtc" if cameras.active_id and "webrtc" in cameras.active_id else "server",
    }


@router.get("/camera/focus-modes")
async def camera_focus_modes(request: Request):
    """List the gphoto2 capture camera's available focus modes (for the admin UI)."""
    cameras = request.app.state.cameras
    cam = cameras.capture_camera or cameras.preview_camera
    fn = getattr(cam, "list_focus_modes", None)
    if cam is None or fn is None:
        return {"available": False, "reason": "Kein gphoto2-Kamera aktiv", "choices": [], "current": ""}
    import asyncio
    return await asyncio.to_thread(fn)


@router.post("/camera/switch/{camera_id:path}")
async def switch_camera(
    camera_id: str,
    request: Request,
    _user=Depends(require_role("admin", "organizer")),
):
    """Switch the active camera (must already be loaded)."""
    cameras = request.app.state.cameras
    success = await cameras.switch(camera_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    mode = "webrtc" if "webrtc" in camera_id else "server"
    await request.app.state.ws_manager.broadcast("camera.switched", {"camera": camera_id, "mode": mode})
    return {"status": "ok", "active": camera_id, "mode": mode}


@router.post("/camera/activate")
async def activate_camera(
    body: dict,
    request: Request,
    _user=Depends(require_role("admin", "organizer")),
):
    """Activate a camera at runtime.

    Body: {"type": "opencv", "device_index": 0, "role": "both"}
    role: "preview" | "capture" | "both" (default: "both")
    """
    cam_type = body.get("type", "")
    if not cam_type:
        raise HTTPException(status_code=400, detail="'type' required (webrtc, opencv, gphoto2, digicamcontrol)")

    role = body.get("role", "both")
    config = {k: v for k, v in body.items() if k not in ("type", "role")}
    config["enabled"] = True

    cameras = request.app.state.cameras
    try:
        cam_id = await cameras.activate_camera(cam_type, config, role=role)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    preview_mode = "webrtc" if cameras.active_id and "webrtc" in cameras.active_id else "server"
    await request.app.state.ws_manager.broadcast("camera.switched", {
        "camera": cam_id, "role": role, "mode": preview_mode,
    })
    return {
        "status": "ok",
        "active": cam_id,
        "role": role,
        "mode": preview_mode,
        "preview": cameras.active_id,
        "capture": cameras.capture_id or cameras.active_id,
    }


# ── Output / Sharing ─────────────────────────────────────────────────────

@router.post("/outputs/send")
async def send_output(
    body: dict,
    request: Request,
    session: Session = Depends(get_session),
):
    """Send a photo via an output module (email, print, etc.)."""
    from app.models import OutputJob

    photo_id = body.get("photo_id")
    collage_id = body.get("collage_id")
    module_id = body.get("module", "")
    target = body.get("target")

    if not photo_id and not collage_id:
        raise HTTPException(status_code=400, detail="photo_id or collage_id required")

    outputs = request.app.state.outputs
    cfg = request.app.state.config

    # Resolve photo path
    photo_path = ""
    photo = None
    if photo_id:
        photo = session.get(Photo, photo_id)
        if photo is None:
            raise HTTPException(status_code=404, detail="Photo not found")
        photo_path = str(Path(cfg["photos"]["storage_path"]) / photo.filename)

    # Per-template print routing: if this is a collage whose template is linked to
    # a *print* preset, print on that preset's printer/paper instead of the global
    # default (e.g. the 3-photo strip → panorama printer).
    print_override = {}
    if module_id == "output.printer" and photo is not None:
        print_override = _print_override_for_photo(photo, session)

    # Low-media guard: warn when the *target* printer is running low, and STOP
    # just before zero so we don't shoot the last sheet/ribbon panel blind.
    media_guard = None
    if module_id == "output.printer" and body.get("mode") != "browser":
        media_guard = _printer_media_guard(cfg, print_override)
        if media_guard:
            _telegram_media_alert(media_guard)   # notify operator (throttled)
        if media_guard and media_guard.get("block"):
            return {"status": "blocked", "message": media_guard["message"],
                    "warning": media_guard["message"], "remaining": media_guard.get("remaining"),
                    "printer": media_guard.get("printer")}

    # Create output job
    job = OutputJob(
        photo_id=photo_id,
        collage_id=collage_id,
        module=module_id,
        status="processing",
        target=target,
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    # Send via module
    result = await outputs.send(module_id, photo_path,
                               {"target": target, "photo_id": photo_id, **print_override})

    job.status = "completed" if result.get("status") == "ok" else "failed"
    job.error_msg = result.get("message")
    session.add(job)
    session.commit()

    await request.app.state.bus.emit("output.completed", {
        "module": module_id, "photo_id": photo_id, "status": job.status
    })

    # Surface a low-media warning alongside a successful print.
    if media_guard and media_guard.get("warn") and result.get("status") == "ok":
        result.setdefault("warning", media_guard["message"])
        result.setdefault("remaining", media_guard.get("remaining"))

    return {"job_id": job.id, "status": job.status, **result}


def _printer_media_guard(cfg: dict, print_override: dict) -> dict | None:
    """Remaining-media check for the printer a job will actually use.

    Returns ``{"block": True, ...}`` when at/under ``block_remaining`` (refuse to
    print, keep a buffer before zero), ``{"warn": True, ...}`` when at/under
    ``warn_remaining`` (print but warn), or ``None`` when there's plenty / the
    printer doesn't report remaining media (e.g. non-dye-sub, or non-Linux).
    """
    from app.modules.output.printer import PrinterOutput

    pcfg = (cfg.get("outputs", {}) or {}).get("printer", {}) or {}
    name = (print_override or {}).get("printer_name") or pcfg.get("printer_name") or ""
    try:
        status = PrinterOutput.printer_status(name)
    except Exception:
        return None
    remaining = (status.get("media") or {}).get("remaining_prints")
    if remaining is None:
        return None
    try:
        warn_at = int(pcfg.get("warn_remaining", 10))
        block_at = int(pcfg.get("block_remaining", 1))
    except (TypeError, ValueError):
        warn_at, block_at = 10, 1
    printer = status.get("printer") or name
    if remaining <= block_at:
        return {"block": True, "remaining": remaining, "printer": printer,
                "message": f"Druck gestoppt — nur noch {remaining} Blatt/Drucke. "
                           "Bitte Medium/Farbband wechseln."}
    if remaining <= warn_at:
        return {"warn": True, "remaining": remaining, "printer": printer,
                "message": f"Nur noch {remaining} Drucke übrig — bitte bald Medium wechseln."}
    return None


def _telegram_media_alert(guard: dict) -> None:
    """Notify the operator via Telegram when a printer is low/empty (throttled to
    at most once per 15 min per printer+level). Fire-and-forget."""
    from app.services.telegram_service import get_telegram

    svc = get_telegram()
    if not svc.ready or not svc.notify_media_enabled:
        return
    printer = guard.get("printer") or "Drucker"
    remaining = guard.get("remaining")
    if guard.get("block"):
        key = f"media-empty:{printer}"
        msg = (f"🖨️ <b>Drucker leer</b>: {printer} — nur noch {remaining} Blatt/Drucke. "
               "Druck gestoppt, bitte Medium/Farbband wechseln.")
    else:
        key = f"media-low:{printer}"
        msg = f"🖨️ <b>Drucker fast leer</b>: {printer} — noch {remaining} Drucke übrig."
    try:
        asyncio.create_task(asyncio.to_thread(svc.notify_throttled, key, msg, 900.0))
    except RuntimeError:                       # no running loop (e.g. tests)
        svc.notify_throttled(key, msg, 900.0)


@router.get("/outputs/available")
async def list_available_outputs(request: Request):
    """List available output modules."""
    return request.app.state.outputs.list_outputs()


def _print_override_for_photo(photo, session: Session) -> dict:
    """If *photo* is a collage from a template linked to a print preset, return
    the per-job printer settings to apply; otherwise an empty dict."""
    import json as _json

    from app.models import OutputPreset, Template

    try:
        meta = _json.loads(photo.metadata_json or "{}")
    except (ValueError, TypeError):
        return {}
    template_id = meta.get("template_id")
    if not template_id:
        return {}
    template = session.get(Template, template_id)
    if template is None or template.preset_id is None:
        return {}
    preset = session.get(OutputPreset, template.preset_id)
    if preset is None or preset.kind != "print":
        return {}

    override = {
        "mode": "server",
        "copies": preset.copies,
        "orientation": preset.orientation,
        "margin_mm": preset.margin_mm,
        "fit_to_page": preset.fit_to_page,
    }
    if preset.printer_name:
        override["printer_name"] = preset.printer_name
    if preset.paper_size:
        override["paper_size"] = preset.paper_size
    return override


# ── Photo access ──────────────────────────────────────────────────────────

@router.get("/photos/feed.json")
def photos_feed(limit: int = 300, session: Session = Depends(get_session)):
    """Public newest-first photo feed for the active event — drives the live
    web gallery (polled by the standalone viewer page). Declared before the
    ``/photos/{photo_id}`` route so "feed.json" isn't parsed as an id."""
    event = session.exec(select(Event).where(Event.is_active == True)).first()
    if event is None:
        return {"event": None, "photos": []}
    limit = max(1, min(1000, int(limit)))
    photos = session.exec(
        select(Photo)
        .join(PhotoSession)
        .where(PhotoSession.event_id == event.id)
        .order_by(Photo.captured_at.desc())
        .limit(limit)
    ).all()
    return {
        "event": event.name,
        "photos": [
            {
                "id": p.id,
                "url": f"/api/v1/photos/{p.id}/file",
                "gif": f"/api/v1/photos/{p.id}/gif" if p.gif_filename else None,
                "thumb": f"/api/v1/photos/{p.id}/thumb" if p.thumbnail else f"/api/v1/photos/{p.id}/file",
                "name": p.filename,
                "ts": p.captured_at.isoformat() if p.captured_at else None,
            }
            for p in photos
        ],
    }


@router.get("/photos/{photo_id}", response_model=PhotoResponse)
def get_photo(photo_id: int, session: Session = Depends(get_session)):
    photo = session.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    return photo


@router.get("/photos/{photo_id}/file")
def get_photo_file(photo_id: int, request: Request, session: Session = Depends(get_session)):
    photo = session.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    cfg = request.app.state.config
    filepath = Path(cfg["photos"]["storage_path"]) / photo.filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")

    # Build a nice download filename from template
    from app.services.filename_service import build_filename
    dl_template = cfg.get("photos", {}).get("download_filename_template", "{event}_{date}_{time}")
    event = session.exec(
        select(Event).join(PhotoSession).where(PhotoSession.id == photo.session_id)
    ).first()
    dl_name = build_filename(dl_template, event_slug=event.slug if event else "photo", now=photo.captured_at)
    return FileResponse(filepath, media_type="image/jpeg", filename=dl_name)


@router.get("/photos/{photo_id}/gif")
def get_photo_gif(photo_id: int, request: Request, session: Session = Depends(get_session)):
    """Download the animated GIF for a photo."""
    photo = session.get(Photo, photo_id)
    if photo is None or not photo.gif_filename:
        raise HTTPException(status_code=404, detail="GIF not found")
    cfg = request.app.state.config
    filepath = Path(cfg["photos"]["storage_path"]) / photo.gif_filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="GIF file not found")

    from app.services.filename_service import build_filename
    dl_template = cfg.get("photos", {}).get("download_filename_template", "{event}_{date}_{time}")
    event = session.exec(
        select(Event).join(PhotoSession).where(PhotoSession.id == photo.session_id)
    ).first()
    dl_name = build_filename(dl_template, event_slug=event.slug if event else "photo", now=photo.captured_at, extension=".gif")
    return FileResponse(filepath, media_type="image/gif", filename=dl_name)


@router.get("/photos/{photo_id}/thumb")
def get_photo_thumb(photo_id: int, request: Request, session: Session = Depends(get_session)):
    photo = session.get(Photo, photo_id)
    if photo is None or not photo.thumbnail:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    cfg = request.app.state.config
    filepath = Path(cfg["photos"]["storage_path"]) / photo.thumbnail
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(filepath, media_type="image/jpeg")


@router.delete("/photos/{photo_id}", status_code=204)
def delete_photo(
    photo_id: int,
    session: Session = Depends(get_session),
):
    from app.config import get_config, get_nested

    cfg = get_config()
    delete_mode = get_nested(cfg, "gallery.delete_mode", "off")

    if delete_mode == "off":
        raise HTTPException(status_code=403, detail="Löschen ist deaktiviert")

    photo = session.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    if delete_mode == "recent":
        minutes = get_nested(cfg, "gallery.delete_recent_minutes", 5)
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        if photo.captured_at < cutoff:
            raise HTTPException(status_code=403, detail="Foto ist zu alt zum Löschen")

    try:
        # Remove dependent rows first (FK: OutputJob.photo_id, CollagePhoto.photo_id)
        from app.models import CollagePhoto, OutputJob
        for oj in session.exec(select(OutputJob).where(OutputJob.photo_id == photo_id)).all():
            session.delete(oj)
        for cp in session.exec(select(CollagePhoto).where(CollagePhoto.photo_id == photo_id)).all():
            session.delete(cp)

        # Delete the files from disk too
        storage = Path(cfg["photos"]["storage_path"])
        for rel in (photo.filename, photo.thumbnail, photo.gif_filename):
            if rel:
                try:
                    (storage / rel).unlink(missing_ok=True)
                except OSError:
                    pass

        session.delete(photo)
        session.commit()
    except Exception as e:
        session.rollback()
        import logging
        logging.getLogger(__name__).exception("delete_photo failed for id=%s", photo_id)
        raise HTTPException(status_code=500, detail=f"Löschen fehlgeschlagen: {e}")


# ── Gallery ───────────────────────────────────────────────────────────────

@router.get("/gallery/{event_slug}", response_model=list[PhotoResponse])
def get_gallery(
    event_slug: str,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    event = session.exec(select(Event).where(Event.slug == event_slug)).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    photos = session.exec(
        select(Photo)
        .join(PhotoSession)
        .where(PhotoSession.event_id == event.id)
        .order_by(Photo.captured_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return photos


@router.get("/gallery/{event_slug}/latest", response_model=list[PhotoResponse])
def get_latest_photos(
    event_slug: str,
    count: int = 10,
    session: Session = Depends(get_session),
):
    event = session.exec(select(Event).where(Event.slug == event_slug)).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    photos = session.exec(
        select(Photo)
        .join(PhotoSession)
        .where(PhotoSession.event_id == event.id)
        .order_by(Photo.captured_at.desc())
        .limit(count)
    ).all()
    return photos


def _generate_thumbnail(filepath: Path, thumb_dir: Path, size: list[int]) -> Path | None:
    """Generate a thumbnail synchronously (called via to_thread)."""
    try:
        from PIL import Image

        img = Image.open(filepath)
        img.thumbnail(tuple(size))
        thumb_path = thumb_dir / f"{filepath.stem}_thumb.jpg"
        img.save(thumb_path, "JPEG", quality=75)
        img.close()
        return thumb_path
    except Exception:
        return None
