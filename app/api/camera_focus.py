"""Scharfstell-Assistent (Admin → Kamera).

Scharfstellen und Festhalten ist bewusst eine Aufgabe für den Menschen: bei
Canon sitzt der AF/MF-Schalter am Objektiv, Software kann ihn nicht umlegen.
Diese Endpunkte helfen nur dabei:

* ``POST /autofocus`` — einmal Autofokus auslösen (gphoto2: autofocusdrive),
* ``POST /zoom`` — Live-View-Lupe der Kamera (Canon: eoszoom 1/5/10),
* ``POST /test-photo`` — Testfoto zum Heranzoomen; landet NICHT in Galerie
  oder Druck (bei capture_target=1 bleibt es nur auf der Speicherkarte),
* ``GET /info`` — was die Kamera kann, und ob sie "Manual" (MF) meldet.

Alles läuft als Auftrag im Kamera-Thread (``cam.call`` / ``cam.capture``).
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import Response

from app.auth import require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/camera/focus", tags=["camera"])

_admin = Depends(require_role("admin", "organizer"))


def _capture_cam(request: Request):
    cameras = request.app.state.cameras
    return cameras.capture_camera or cameras.preview_camera


@router.get("/info")
async def focus_info(request: Request, _user=_admin):
    cameras = request.app.state.cameras
    cam = _capture_cam(request)
    preview_id = cameras.active_id or ""
    capture_id = cameras.capture_id or preview_id
    base = {
        "camera": capture_id,
        # Lupe/Live-Ausschnitt zeigt die Vorschau-Kamera — nur aussagekräftig,
        # wenn sie auch das Foto macht.
        "same_camera": capture_id == preview_id,
        "server_preview": bool(preview_id) and "webrtc" not in preview_id,
        "has_camera": cam is not None,
    }
    fn = getattr(cam, "focus_info", None)
    if cam is None or fn is None:
        return {**base, "available": False, "autofocus": False, "zoom": False,
                "focus_mode": "", "manual": False}
    info = await fn()
    if base["same_camera"] is False:
        info["zoom"] = False  # Kamera-Lupe wirkt nicht auf die Vorschau-Kamera
    return {**base, **info}


@router.post("/autofocus")
async def focus_autofocus(request: Request, _user=_admin):
    cam = _capture_cam(request)
    fn = getattr(cam, "autofocus_now", None)
    if cam is None or fn is None:
        raise HTTPException(status_code=400, detail="Kamera kann den Autofokus nicht per Software auslösen")
    return await fn()


@router.post("/zoom")
async def focus_zoom(request: Request, body: dict = Body(default={}), _user=_admin):
    cam = _capture_cam(request)
    fn = getattr(cam, "set_liveview_zoom", None)
    if cam is None or fn is None:
        return {"ok": False, "message": "Kamera-Lupe nicht verfügbar"}
    try:
        level = int(body.get("level", 1))
    except (TypeError, ValueError):
        level = 1
    return await fn(level)


@router.post("/test-photo")
async def focus_test_photo(request: Request, _user=_admin):
    """Ein Foto nur zum Prüfen der Schärfe — wird nirgends gespeichert."""
    cam = _capture_cam(request)
    if cam is None:
        raise HTTPException(status_code=503, detail="Keine Kamera aktiv")
    try:
        data = await asyncio.wait_for(cam.capture(), timeout=30.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Kamera hat nicht ausgelöst (Zeitüberschreitung)")
    except Exception as e:
        logger.warning("Testfoto fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail=f"Testfoto fehlgeschlagen: {e}")
    if not data:
        raise HTTPException(status_code=500, detail="Kamera hat kein Bild geliefert")
    return Response(content=data, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})
