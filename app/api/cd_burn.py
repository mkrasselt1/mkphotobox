"""CD/DVD burning API — burn an event's (or all) photos to disc."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import require_role
from app.config import get_config, set_nested
from app.services.cd_burn_service import (
    get_burn_service,
    probe_media,
    xorriso_available,
)
from app.services.photo_export import gather_files, list_event_sources

router = APIRouter(prefix="/api/v1/cd-burn", tags=["cd-burn"])


def _cfg() -> dict:
    return get_config().get("cd_burn", {})


@router.get("/status")
async def cd_burn_status():
    """Drive/media info, burner availability, and current job state."""
    cfg = _cfg()
    device = cfg.get("device", "/dev/sr0")
    media = await asyncio.to_thread(probe_media, device)
    service = get_burn_service()
    return {
        "available": xorriso_available(),
        "config": {
            "device": device,
            "volume_label": cfg.get("volume_label", "PHOTOBOX"),
            "speed": cfg.get("speed", ""),
            "include_gifs": cfg.get("include_gifs", True),
            "eject_when_done": cfg.get("eject_when_done", True),
        },
        "media": media,
        "job": service.state,
        "busy": service.is_busy,
    }


@router.get("/sources")
def cd_burn_sources(_user=Depends(require_role("admin", "organizer"))):
    """List events with photo counts plus the total, to pick what to burn."""
    return list_event_sources()


@router.post("/burn")
async def cd_burn_start(body: dict, request: Request,
                        _user=Depends(require_role("admin", "organizer"))):
    """Start a burn job.

    Body: {scope: "event"|"all", event_id?: int}
    """
    if not xorriso_available():
        raise HTTPException(status_code=400, detail="xorriso ist nicht installiert.")

    cfg = _cfg()
    scope = body.get("scope", "all")
    event_id = body.get("event_id")
    include_gifs = cfg.get("include_gifs", True)

    try:
        files = gather_files(scope, event_id, include_gifs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not files:
        raise HTTPException(status_code=400, detail="Keine Fotos zum Brennen gefunden.")

    service = get_burn_service()
    result = await service.start(
        files,
        device=cfg.get("device", "/dev/sr0"),
        volume_label=cfg.get("volume_label", "PHOTOBOX"),
        speed=str(cfg.get("speed", "") or ""),
        eject=cfg.get("eject_when_done", True),
        bus=request.app.state.bus,
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@router.post("/cancel")
async def cd_burn_cancel(_user=Depends(require_role("admin", "organizer"))):
    return await get_burn_service().cancel()


@router.post("/configure")
def cd_burn_configure(body: dict, _user=Depends(require_role("admin", "organizer"))):
    """Update burner settings (device, label, speed, options)."""
    cfg = get_config()
    allowed = ("device", "volume_label", "speed", "include_gifs", "eject_when_done")
    for key in allowed:
        if key in body:
            set_nested(cfg, f"cd_burn.{key}", body[key])
    return {"status": "ok", **{k: body[k] for k in allowed if k in body}}
