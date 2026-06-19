"""Trigger configuration API — device discovery, learn mode, settings."""

from __future__ import annotations

import asyncio
import logging
import platform
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from app.auth import require_role
from app.database import get_session
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/triggers", tags=["triggers"])


# ── Trigger status ───────────────────────────────────────────────────────

@router.get("/")
def list_triggers(
    request: Request,
    _user: User = Depends(require_role("admin")),
):
    """List all configured triggers and their status."""
    cfg = request.app.state.config
    triggers_cfg = cfg.get("triggers", {})
    loaded = request.app.state.triggers.list_triggers()
    loaded_ids = {t.get("name", "") for t in loaded}

    result = []
    for trig_id, trig_conf in triggers_cfg.items():
        if not isinstance(trig_conf, dict):
            continue
        full_id = f"trigger.{trig_id}"
        result.append({
            "id": trig_id,
            "full_id": full_id,
            "enabled": trig_conf.get("enabled", False),
            "loaded": full_id in loaded_ids,
            "config": {k: v for k, v in trig_conf.items() if k != "enabled"},
        })
    return result


# ── Audio device discovery ───────────────────────────────────────────────

@router.get("/audio-devices")
def list_audio_devices(_user: User = Depends(require_role("admin"))):
    """List available audio input devices for the acoustic trigger."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        inputs = []
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0:
                inputs.append({
                    "index": i,
                    "name": d["name"],
                    "channels": d["max_input_channels"],
                    "sample_rate": d["default_samplerate"],
                    "is_default": i == sd.default.device[0],
                })
        return inputs
    except ImportError:
        return {"error": "sounddevice not installed"}
    except Exception as e:
        return {"error": str(e)}


# ── Serial port discovery ────────────────────────────────────────────────

@router.get("/serial-ports")
def list_serial_ports(_user: User = Depends(require_role("admin"))):
    """List available serial ports on the host."""
    try:
        from serial.tools import list_ports
        ports = list_ports.comports()
        return [
            {
                "port": p.device,
                "name": p.description,
                "hwid": p.hwid,
                "manufacturer": p.manufacturer or "",
            }
            for p in ports
        ]
    except ImportError:
        return {"error": "pyserial not installed"}
    except Exception as e:
        return {"error": str(e)}


# ── Host keyboard device discovery ───────────────────────────────────────

@router.get("/keyboard-devices")
def list_keyboard_devices(_user: User = Depends(require_role("admin"))):
    """List input devices that can act as keyboards on the host."""
    system = platform.system()
    if system == "Linux":
        try:
            import evdev
            devices = []
            for path in evdev.list_devices():
                d = evdev.InputDevice(path)
                caps = d.capabilities(verbose=False)
                if evdev.ecodes.EV_KEY in caps:
                    devices.append({
                        "path": d.path,
                        "name": d.name,
                        "phys": d.phys,
                    })
            return devices
        except ImportError:
            return {"error": "evdev not installed"}
    elif system == "Windows":
        return [{"name": "System keyboard (pynput)", "path": "pynput"}]
    return []


# ── Learn mode: host keyboard ───────────────────────────────────────────

@router.post("/learn/host-keyboard")
async def learn_host_keyboard(
    request: Request,
    _user: User = Depends(require_role("admin")),
):
    """Enter learn mode: waits for the next key press on host input devices.

    Returns the key code and device name after a key is pressed (timeout 15s).
    """
    system = platform.system()

    if system == "Linux":
        return await _learn_evdev()
    elif system == "Windows":
        return await _learn_pynput()
    else:
        raise HTTPException(status_code=400, detail=f"Not supported on {system}")


async def _learn_evdev() -> dict:
    import evdev

    devices = []
    for path in evdev.list_devices():
        d = evdev.InputDevice(path)
        caps = d.capabilities(verbose=False)
        if evdev.ecodes.EV_KEY in caps:
            devices.append(d)

    if not devices:
        raise HTTPException(status_code=404, detail="No input devices found")

    result: dict[str, Any] = {}

    async def read_one(device):
        async for event in device.async_read_loop():
            if event.type == evdev.ecodes.EV_KEY and event.value == 1:
                key_name = evdev.ecodes.KEY.get(event.code, f"KEY_{event.code}")
                if isinstance(key_name, list):
                    key_name = key_name[0]
                result["key_code"] = str(key_name)
                result["key_event_code"] = event.code
                result["device"] = device.name
                return

    tasks = [asyncio.create_task(read_one(d)) for d in devices]
    try:
        done, pending = await asyncio.wait(tasks, timeout=15.0, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
    except asyncio.CancelledError:
        pass

    if not result:
        raise HTTPException(status_code=408, detail="Timeout — keine Taste gedrückt")

    return result


async def _learn_pynput() -> dict:
    from pynput import keyboard

    result: dict[str, Any] = {}
    event = asyncio.Event()
    loop = asyncio.get_event_loop()

    def on_press(key):
        try:
            key_name = key.char if hasattr(key, 'char') and key.char else str(key).replace("Key.", "")
        except AttributeError:
            key_name = str(key).replace("Key.", "")
        result["key_code"] = key_name
        result["device"] = "pynput"
        loop.call_soon_threadsafe(event.set)
        return False  # Stop listener

    listener = keyboard.Listener(on_press=on_press)
    listener.start()

    try:
        await asyncio.wait_for(event.wait(), timeout=15.0)
    except asyncio.TimeoutError:
        listener.stop()
        raise HTTPException(status_code=408, detail="Timeout — keine Taste gedrückt")

    listener.stop()
    return result


# ── Learn mode: serial ───────────────────────────────────────────────────

@router.post("/learn/serial")
async def learn_serial(
    body: dict,
    _user: User = Depends(require_role("admin")),
):
    """Listen on a serial port and return the first data received.

    Body: {"port": "/dev/ttyUSB0", "baud": 9600}
    """
    port = body.get("port", "")
    baud = body.get("baud", 9600)
    if not port:
        raise HTTPException(status_code=400, detail="'port' required")

    try:
        import serial
    except ImportError:
        raise HTTPException(status_code=400, detail="pyserial not installed")

    result: dict[str, Any] = {}

    def read_serial():
        try:
            ser = serial.Serial(port, baud, timeout=0.5)
            deadline = asyncio.get_event_loop().time() + 15.0
            buffer = b""
            while asyncio.get_event_loop().time() < deadline:
                data = ser.read(64)
                if data:
                    buffer += data
                    result["raw_bytes"] = buffer.hex()
                    result["text"] = buffer.decode("utf-8", errors="replace").strip()
                    result["port"] = port
                    ser.close()
                    return
            ser.close()
        except Exception as e:
            result["error"] = str(e)

    await asyncio.to_thread(read_serial)

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    if not result:
        raise HTTPException(status_code=408, detail="Timeout — keine Daten empfangen")

    return result
