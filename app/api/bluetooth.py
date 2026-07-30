"""Bluetooth API — visibility, paired devices, sending and received files."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import require_role
from app.services import bluetooth_service

router = APIRouter(prefix="/api/v1/bluetooth", tags=["bluetooth"])


def _bt_config(request: Request) -> dict:
    return (request.app.state.config.get("outputs", {}) or {}).get("bluetooth", {}) or {}


@router.get("/status")
async def bluetooth_status(request: Request):
    """Adapter state plus whether the box is currently accepting files."""
    config = _bt_config(request)
    adapter, receiver = await asyncio.gather(
        asyncio.to_thread(bluetooth_service.adapter_status),
        asyncio.to_thread(bluetooth_service.receiver_status, config),
    )
    return {"adapter": adapter, "receiver": receiver}


@router.get("/devices")
async def bluetooth_devices():
    """Paired devices — listed whether present or not (admin view)."""
    devices = await asyncio.to_thread(bluetooth_service.paired_devices)
    return {"available": bluetooth_service.available(), "devices": devices}


@router.get("/scan")
async def bluetooth_scan(duration: int = 10):
    """Devices in range right now — what the booth picker offers guests.

    Unauthenticated on purpose: the booth share screen runs without a login,
    same as the other guest-facing output endpoints.
    """
    duration = max(3, min(int(duration), 30))
    devices = await asyncio.to_thread(bluetooth_service.nearby_devices, duration)
    return {"available": bluetooth_service.available(), "devices": devices}


@router.post("/visible")
async def bluetooth_visible(body: dict, _user=Depends(require_role("admin", "organizer"))):
    """Make the booth discoverable/pairable for phones: {on: bool}."""
    return await asyncio.to_thread(bluetooth_service.set_visible, bool(body.get("on", True)))


@router.get("/received")
async def bluetooth_received(request: Request, _user=Depends(require_role("admin", "organizer"))):
    """Files guests have pushed to the box."""
    config = _bt_config(request)
    files = await asyncio.to_thread(bluetooth_service.list_received, config)
    return {"directory": str(bluetooth_service.receive_dir(config)), "files": files}


@router.post("/send")
async def bluetooth_send(body: dict, _user=Depends(require_role("admin", "organizer"))):
    """Push a file to a paired device: {address, path}."""
    address = (body.get("address") or "").strip()
    path = (body.get("path") or "").strip()
    if not address or not path:
        raise HTTPException(status_code=400, detail="address und path sind erforderlich")
    return await asyncio.to_thread(bluetooth_service.send_file, address, path)
