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
