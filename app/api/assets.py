"""Asset import & management API — backgrounds, frames, logos, stickers."""

from __future__ import annotations

import asyncio
import mimetypes

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.auth import require_role
from app.services import asset_service

router = APIRouter(prefix="/api/v1/assets", tags=["assets"])


@router.get("/sources")
def asset_sources(_user=Depends(require_role("admin", "organizer"))):
    """Browsable sources: local import folder + removable drives."""
    return {"sources": asset_service.list_sources()}


@router.get("/browse")
async def asset_browse(path: str, _user=Depends(require_role("admin", "organizer"))):
    """List subfolders and image files in *path* (restricted to allowed roots)."""
    try:
        return await asyncio.to_thread(asset_service.browse, path)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/import")
async def asset_import(body: dict, _user=Depends(require_role("admin", "organizer"))):
    """Import files: {type, paths: [...]}."""
    asset_type = body.get("type", "")
    paths = body.get("paths", [])
    if not paths:
        raise HTTPException(status_code=400, detail="Keine Dateien ausgewählt.")
    try:
        created = await asyncio.to_thread(asset_service.import_files, asset_type, paths)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "imported": len(created), "assets": created}


@router.get("")
def asset_list(type: str | None = None, _user=Depends(require_role("admin", "organizer"))):
    """List imported assets, optionally filtered by type."""
    return {"assets": asset_service.list_assets(type)}


@router.get("/{asset_id}/file")
def asset_file(asset_id: int):
    path = asset_service.get_asset_file(asset_id, thumb=False)
    if path is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    media = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return FileResponse(path, media_type=media)


@router.get("/{asset_id}/thumb")
def asset_thumb(asset_id: int):
    path = asset_service.get_asset_file(asset_id, thumb=True)
    if path is None:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(path, media_type="image/jpeg")


@router.delete("/{asset_id}", status_code=204)
def asset_delete(asset_id: int, _user=Depends(require_role("admin", "organizer"))):
    if not asset_service.delete_asset(asset_id):
        raise HTTPException(status_code=404, detail="Asset not found")
