"""USB / removable media export API — copy photos to a selectable drive."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import require_role
from app.config import get_config, set_nested
from app.services.photo_export import gather_files, list_event_sources
from app.services.usb_export_service import get_export_service, list_drives

router = APIRouter(prefix="/api/v1/usb-export", tags=["usb-export"])


def _cfg() -> dict:
    return get_config().get("usb_export", {})


@router.get("/status")
async def usb_status():
    """Current config and copy-job state."""
    cfg = _cfg()
    service = get_export_service()
    return {
        "config": {
            "subfolder": cfg.get("subfolder", "Photobox"),
            "include_gifs": cfg.get("include_gifs", True),
        },
        "job": service.state,
        "busy": service.is_busy,
    }


@router.get("/drives")
async def usb_drives(_user=Depends(require_role("admin", "organizer"))):
    """List mounted removable media (USB drives, SD cards, USB sticks)."""
    drives = await asyncio.to_thread(list_drives)
    return {"drives": drives}


@router.get("/sources")
def usb_sources(_user=Depends(require_role("admin", "organizer"))):
    """List events with photo counts, to pick what to copy."""
    return list_event_sources()


@router.post("/copy")
async def usb_copy(body: dict, request: Request,
                   _user=Depends(require_role("admin", "organizer"))):
    """Start a copy job.

    Body: {mountpoint: str, scope: "event"|"all", event_id?: int}
    """
    cfg = _cfg()
    mountpoint = body.get("mountpoint", "")
    if not mountpoint:
        raise HTTPException(status_code=400, detail="Kein Zielmedium ausgewählt.")

    scope = body.get("scope", "all")
    event_id = body.get("event_id")
    include_gifs = cfg.get("include_gifs", True)

    try:
        files = gather_files(scope, event_id, include_gifs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not files:
        raise HTTPException(status_code=400, detail="Keine Fotos zum Kopieren gefunden.")

    service = get_export_service()

    # Pre-flight: refuse if the chosen medium is too small
    drives = await asyncio.to_thread(list_drives)
    target = next((d for d in drives if d["mountpoint"] == mountpoint), None)
    if target is None:
        raise HTTPException(status_code=400, detail="Zielmedium nicht (mehr) verfügbar.")
    space_err = service.validate_space(files, target.get("free_bytes"))
    if space_err:
        raise HTTPException(status_code=400, detail=space_err)

    result = await service.start(
        files,
        mountpoint=mountpoint,
        subfolder=cfg.get("subfolder", "Photobox"),
        bus=request.app.state.bus,
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@router.post("/cancel")
async def usb_cancel(_user=Depends(require_role("admin", "organizer"))):
    return await get_export_service().cancel()


@router.post("/configure")
def usb_configure(body: dict, _user=Depends(require_role("admin", "organizer"))):
    """Update export settings (subfolder, include_gifs)."""
    cfg = get_config()
    for key in ("subfolder", "include_gifs"):
        if key in body:
            set_nested(cfg, f"usb_export.{key}", body[key])
    return {"status": "ok", **{k: body[k] for k in ("subfolder", "include_gifs") if k in body}}
