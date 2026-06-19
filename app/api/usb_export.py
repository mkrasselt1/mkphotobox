"""USB / removable media export API — copy photos to a selectable drive."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from app.auth import require_role
from app.config import (
    export_settings_bundle,
    get_config,
    import_settings_bundle,
    set_nested,
)
from app.database import get_session
from app.services.photo_export import gather_files, list_event_sources
from app.services.usb_export_service import get_export_service, list_drives

router = APIRouter(prefix="/api/v1/usb-export", tags=["usb-export"])

SETTINGS_FILENAME = "photobox-settings.json"


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


async def _require_drive(mountpoint: str) -> None:
    if not mountpoint:
        raise HTTPException(status_code=400, detail="Kein Zielmedium ausgewählt.")
    drives = await asyncio.to_thread(list_drives)
    if not any(d["mountpoint"] == mountpoint for d in drives):
        raise HTTPException(status_code=400, detail="Zielmedium nicht (mehr) verfügbar.")


@router.get("/settings/check")
async def usb_settings_check(mountpoint: str,
                            _user=Depends(require_role("admin", "organizer"))):
    """Report whether a settings file exists on the given medium (for import)."""
    sub = _cfg().get("subfolder", "Photobox")
    for path in (Path(mountpoint) / SETTINGS_FILENAME, Path(mountpoint) / sub / SETTINGS_FILENAME):
        if path.is_file():
            return {"found": True, "path": str(path)}
    return {"found": False}


@router.post("/settings/export")
async def usb_export_settings(body: dict, session: Session = Depends(get_session),
                             _user=Depends(require_role("admin", "organizer"))):
    """Write a settings backup (config + DB settings) to the chosen medium."""
    mountpoint = body.get("mountpoint", "")
    await _require_drive(mountpoint)
    bundle = export_settings_bundle(session, include_secret=bool(body.get("include_secret")))
    dest = Path(mountpoint) / SETTINGS_FILENAME

    def _write() -> None:
        dest.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        await asyncio.to_thread(_write)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Schreiben fehlgeschlagen: {e}")
    return {"status": "ok", "path": str(dest), "db_settings": len(bundle["db_settings"])}


@router.post("/settings/import")
async def usb_import_settings(body: dict, request: Request,
                             session: Session = Depends(get_session),
                             _user=Depends(require_role("admin"))):
    """Restore settings from a backup file on the chosen medium."""
    mountpoint = body.get("mountpoint", "")
    if not mountpoint:
        raise HTTPException(status_code=400, detail="Kein Medium ausgewählt.")
    sub = _cfg().get("subfolder", "Photobox")
    path = next((p for p in (Path(mountpoint) / SETTINGS_FILENAME,
                             Path(mountpoint) / sub / SETTINGS_FILENAME) if p.is_file()), None)
    if path is None:
        raise HTTPException(status_code=404, detail="Keine Einstellungs-Datei auf dem Medium gefunden.")
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
        result = import_settings_bundle(session, bundle)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import fehlgeschlagen: {e}")
    # make the freshly merged config live for endpoints reading app.state.config
    request.app.state.config = get_config()
    return {"status": "ok", **result}


@router.post("/configure")
def usb_configure(body: dict, _user=Depends(require_role("admin", "organizer"))):
    """Update export settings (subfolder, include_gifs)."""
    cfg = get_config()
    for key in ("subfolder", "include_gifs"):
        if key in body:
            set_nested(cfg, f"usb_export.{key}", body[key])
    return {"status": "ok", **{k: body[k] for k in ("subfolder", "include_gifs") if k in body}}
