"""Background removal API endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import Response

from app.auth import require_role
from app.config import get_config, set_nested

router = APIRouter(prefix="/api/v1/background", tags=["background"])


def _get_bg_remover(request: Request):
    """Get the BackgroundRemover from the active OpenCV camera."""
    cameras = request.app.state.cameras
    cam = cameras.preview_camera or cameras.capture_camera
    if cam is None or not hasattr(cam, "bg_remover"):
        raise HTTPException(status_code=400, detail="Background removal needs an OpenCV camera")
    return cam.bg_remover


@router.get("/status")
def get_status(request: Request):
    """Get background removal status."""
    try:
        remover = _get_bg_remover(request)
        return remover.get_status()
    except HTTPException:
        return {"enabled": False, "mode": "none", "message": "No OpenCV camera active"}


@router.post("/enable")
def enable_bg_removal(
    body: dict,
    request: Request,
    _user=Depends(require_role("admin", "organizer")),
):
    """Enable/disable background removal.

    Body: {"enabled": true, "mode": "chromakey"} or {"enabled": true, "mode": "reference"}
    """
    remover = _get_bg_remover(request)
    enabled = body.get("enabled", True)
    mode = body.get("mode", remover.mode)

    remover._enabled = enabled
    remover._mode = mode if enabled else "none"

    # Persist to in-memory config
    cfg = get_config()
    set_nested(cfg, "background_removal.enabled", enabled)
    set_nested(cfg, "background_removal.mode", mode if enabled else "none")

    return remover.get_status()


@router.post("/capture-reference")
async def capture_reference(
    request: Request,
    _user=Depends(require_role("admin", "organizer")),
):
    """Capture current camera frame as the background reference (raw, no BG removal)."""
    cameras = request.app.state.cameras
    cam = cameras.preview_camera
    if cam is None:
        raise HTTPException(status_code=400, detail="No preview camera")

    if not hasattr(cam, "get_raw_frame"):
        raise HTTPException(status_code=400, detail="Camera does not support raw frame access")

    import cv2

    # Get raw frame directly from camera (bypasses all transforms including BG removal)
    raw_frame = await asyncio.to_thread(cam.get_raw_frame)
    if raw_frame is None:
        raise HTTPException(status_code=500, detail="Failed to capture frame")

    remover = _get_bg_remover(request)
    remover.set_reference_from_frame(raw_frame)

    # Save reference image
    ref_path = Path(get_config()["photos"]["storage_path"]) / "bg_reference.jpg"
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(lambda: cv2.imwrite(str(ref_path), raw_frame))

    cfg = get_config()
    set_nested(cfg, "background_removal.reference_image", str(ref_path))

    return {"status": "ok", "message": "Reference captured", **remover.get_status()}


@router.post("/upload-reference")
async def upload_reference(
    request: Request,
    file: UploadFile = File(...),
    _user=Depends(require_role("admin", "organizer")),
):
    """Upload an image as background reference."""
    import cv2
    import numpy as np

    data = await file.read()
    nparr = np.frombuffer(data, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Invalid image")

    remover = _get_bg_remover(request)
    remover.set_reference_from_frame(frame)

    ref_path = Path(get_config()["photos"]["storage_path"]) / "bg_reference.jpg"
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(ref_path), frame)

    cfg = get_config()
    set_nested(cfg, "background_removal.reference_image", str(ref_path))

    return {"status": "ok", "message": "Reference uploaded", **remover.get_status()}


@router.post("/pick-color")
async def pick_chromakey_color(
    body: dict,
    request: Request,
    _user=Depends(require_role("admin", "organizer")),
):
    """Set chroma key color from pixel coordinates or direct BGR value.

    Body: {"x": 100, "y": 100} (picks from current frame)
    or:   {"b": 0, "g": 255, "r": 0} (direct BGR)
    """
    remover = _get_bg_remover(request)

    picked_bgr = None

    if "b" in body and "g" in body and "r" in body:
        picked_bgr = (int(body["b"]), int(body["g"]), int(body["r"]))
        remover.set_chromakey_from_pixel(picked_bgr)
    elif "x" in body and "y" in body:
        # Pick from current raw camera frame (no BG removal applied)
        cameras = request.app.state.cameras
        cam = cameras.preview_camera
        if cam is None:
            raise HTTPException(status_code=400, detail="No camera")

        import numpy as np

        if hasattr(cam, "get_raw_frame"):
            frame = await asyncio.to_thread(cam.get_raw_frame)
        else:
            import cv2
            frame_bytes = await cam.get_preview_frame()
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            raise HTTPException(status_code=500, detail="Failed to get frame")

        x, y = int(body["x"]), int(body["y"])
        h, w = frame.shape[:2]
        x = max(0, min(x, w - 1))
        y = max(0, min(y, h - 1))

        # Average a small region around the picked pixel for stability
        r = 5
        region = frame[max(0, y - r):min(h, y + r), max(0, x - r):min(w, x + r)]
        avg_bgr = region.mean(axis=(0, 1)).astype(int)
        picked_bgr = tuple(avg_bgr)
        remover.set_chromakey_from_pixel(picked_bgr)
    else:
        raise HTTPException(status_code=400, detail="Provide {x,y} or {b,g,r}")

    cfg = get_config()
    set_nested(cfg, "background_removal.chromakey_hue", remover._key_hue)

    # Convert BGR to RGB hex for the frontend
    b, g, r_val = int(picked_bgr[0]), int(picked_bgr[1]), int(picked_bgr[2])
    hex_color = f"#{r_val:02x}{g:02x}{b:02x}"

    return {
        "status": "ok",
        "picked_color": hex_color,
        "rgb": {"r": r_val, "g": g, "b": b},
        **remover.get_status(),
    }


@router.post("/settings")
def update_settings(
    body: dict,
    request: Request,
    _user=Depends(require_role("admin", "organizer")),
):
    """Update background removal settings.

    Body: {"reference_threshold": 40, "chromakey_tolerance": 30, ...}
    """
    remover = _get_bg_remover(request)
    cfg = get_config()

    for key in ("reference_threshold", "chromakey_tolerance", "chromakey_saturation_min",
                "blur_radius", "feather", "replacement_color"):
        if key in body:
            setattr(remover, f"_{key}", body[key])
            set_nested(cfg, f"background_removal.{key}", body[key])

    return remover.get_status()


@router.post("/upload-replacement")
async def upload_replacement(
    request: Request,
    file: UploadFile = File(...),
    _user=Depends(require_role("admin", "organizer")),
):
    """Upload a replacement background image."""
    import cv2
    import numpy as np

    data = await file.read()
    nparr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Invalid image")

    remover = _get_bg_remover(request)
    repl_path = Path(get_config()["photos"]["storage_path"]) / "bg_replacement.jpg"
    repl_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(repl_path), img)
    remover.load_replacement_image(str(repl_path))

    cfg = get_config()
    set_nested(cfg, "background_removal.replacement_image", str(repl_path))

    return {"status": "ok", "message": "Replacement background uploaded"}


@router.post("/remove-replacement")
def remove_replacement(
    request: Request,
    _user=Depends(require_role("admin", "organizer")),
):
    """Remove the replacement background image, falling back to color."""
    remover = _get_bg_remover(request)
    remover._replacement_image = None

    cfg = get_config()
    set_nested(cfg, "background_removal.replacement_image", "")

    return {"status": "ok", "message": "Replacement image removed", **remover.get_status()}
