"""WiFi management API — scan, connect, disconnect via NetworkManager."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from app.auth import require_role
from app.services import wifi_service

router = APIRouter(prefix="/api/v1/wifi", tags=["wifi"])


@router.get("/status")
async def wifi_status():
    """Current WiFi state (availability, radio, active connection, IP)."""
    return await asyncio.to_thread(wifi_service.get_status)


@router.get("/scan")
async def wifi_scan(rescan: bool = True):
    """List visible WiFi networks."""
    networks = await asyncio.to_thread(wifi_service.scan_networks, rescan)
    return {"available": wifi_service.nmcli_available(), "networks": networks}


@router.post("/connect")
async def wifi_connect(body: dict, _user=Depends(require_role("admin", "organizer"))):
    """Connect to a network: {ssid, password?, hidden?}."""
    return await asyncio.to_thread(
        wifi_service.connect,
        body.get("ssid", ""),
        body.get("password") or None,
        bool(body.get("hidden", False)),
    )


@router.post("/disconnect")
async def wifi_disconnect(_user=Depends(require_role("admin", "organizer"))):
    return await asyncio.to_thread(wifi_service.disconnect)


@router.post("/forget")
async def wifi_forget(body: dict, _user=Depends(require_role("admin", "organizer"))):
    """Delete a saved connection: {ssid}."""
    return await asyncio.to_thread(wifi_service.forget, body.get("ssid", ""))


@router.post("/radio")
async def wifi_radio(body: dict, _user=Depends(require_role("admin", "organizer"))):
    """Turn the WiFi radio on/off: {on: bool}."""
    return await asyncio.to_thread(wifi_service.set_radio, bool(body.get("on", True)))


# ── Gespeicherte Netze ───────────────────────────────────────────────────────

@router.get("/saved")
async def wifi_saved(_user=Depends(require_role("admin", "organizer"))):
    """Saved WiFi profiles (SSID, priority, active) — never any password."""
    return await asyncio.to_thread(wifi_service.list_saved)


@router.post("/saved")
async def wifi_saved_add(body: dict, _user=Depends(require_role("admin", "organizer"))):
    """Save a network without connecting: {ssid, password?, hidden?, priority?}."""
    return await asyncio.to_thread(
        wifi_service.add_saved,
        body.get("ssid", ""),
        body.get("password") or None,
        bool(body.get("hidden", False)),
        body.get("priority"),
    )


@router.delete("/saved/{uuid}")
async def wifi_saved_delete(uuid: str, _user=Depends(require_role("admin", "organizer"))):
    return await asyncio.to_thread(wifi_service.delete_saved, uuid)


@router.post("/saved/{uuid}/priority")
async def wifi_saved_priority(uuid: str, body: dict,
                              _user=Depends(require_role("admin", "organizer"))):
    """Set the autoconnect priority: {priority: int} (higher wins)."""
    return await asyncio.to_thread(wifi_service.set_priority, uuid, body.get("priority"))


@router.post("/saved/{uuid}/connect")
async def wifi_saved_connect(uuid: str, _user=Depends(require_role("admin", "organizer"))):
    """Activate a saved profile now."""
    return await asyncio.to_thread(wifi_service.connect_saved, uuid)
