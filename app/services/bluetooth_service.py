"""Bluetooth file transfer via bluez OBEX Object Push.

Both directions go through bluez's ``obexd``, driven by the ``bt-obex`` CLI from
the *bluez-tools* package:

* **Sending**   ``bt-obex -p <MAC> <file>`` — the phone must already be paired.
* **Receiving** ``bt-obex -s <dir> -y`` runs as a background service unit and
  drops incoming files into ``receive_dir``.

Two things about this stack are easy to get wrong, so they are handled here:

1. ``obexd`` lives on the D-Bus **session** bus, but the app runs as a systemd
   *system* service which has no session. ``scripts/setup.sh`` therefore enables
   lingering for the run user so ``/run/user/<uid>/bus`` always exists, and
   every call gets ``DBUS_SESSION_BUS_ADDRESS`` pointed at it.
2. ``bt-obex -p`` aborts with a failed C assertion (not a clean error) when the
   target MAC is not a device bluez knows. Callers must never reach it with an
   unpaired address, so :func:`send_file` checks the pairing list first.

Linux-only; every entry point degrades to a clear message elsewhere.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TIMEOUT = 20          # bluetoothctl / bt-device queries are fast
_SEND_TIMEOUT = 180    # a photo over OBEX on a bad link can genuinely take a while

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_RECEIVE_DIR = _BASE_DIR / "data" / "bluetooth_in"

RECEIVER_UNIT = "mkphotobox-btrecv.service"
AGENT_UNIT = "mkphotobox-btagent.service"


# ── environment ───────────────────────────────────────────────────────────────

def _session_env() -> dict[str, str]:
    """Environment with the session bus address obexd is reachable on."""
    env = dict(os.environ)
    if "DBUS_SESSION_BUS_ADDRESS" not in env:
        uid = os.getuid()
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"
        env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    return env


def _run(args: list[str], timeout: int = _TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, env=_session_env(),
    )


# ── availability ──────────────────────────────────────────────────────────────

def system_requirement() -> str | None:
    """What's missing before Bluetooth transfer can work here, else None."""
    if platform.system() != "Linux":
        return "Bluetooth-Übertragung gibt es nur unter Linux"
    if not shutil.which("bluetoothctl"):
        return "bluez fehlt — sudo apt install bluez"
    if not shutil.which("bt-obex"):
        return "bt-obex fehlt — sudo apt install bluez-tools"
    return None


def available() -> bool:
    return system_requirement() is None


# ── adapter ───────────────────────────────────────────────────────────────────

def adapter_status() -> dict[str, Any]:
    """Name, address and visibility of the default adapter."""
    req = system_requirement()
    if req:
        return {"available": False, "reason": req}

    status: dict[str, Any] = {
        "available": True, "powered": False, "discoverable": False,
        "pairable": False, "name": None, "address": None,
    }
    try:
        res = _run(["bluetoothctl", "show"])
    except subprocess.TimeoutExpired:
        status["reason"] = "bluetoothctl antwortet nicht"
        return status

    for line in res.stdout.splitlines():
        line = line.strip()
        if line.startswith("Controller "):
            parts = line.split()
            if len(parts) >= 2:
                status["address"] = parts[1]
        elif line.startswith("Name:"):
            status["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("Powered:"):
            status["powered"] = line.endswith("yes")
        elif line.startswith("Discoverable:"):
            status["discoverable"] = line.endswith("yes")
        elif line.startswith("Pairable:"):
            status["pairable"] = line.endswith("yes")

    if not status["address"]:
        status["available"] = False
        status["reason"] = "Kein Bluetooth-Adapter gefunden"
    return status


def set_visible(on: bool) -> dict[str, Any]:
    """Make the box discoverable and pairable (or hide it again).

    The adapter's DiscoverableTimeout defaults to 180s, which would silently
    hide the booth mid-event — so visibility is pinned open while on.
    """
    req = system_requirement()
    if req:
        return {"status": "error", "message": req}

    value = "on" if on else "off"
    try:
        if on:
            _run(["bluetoothctl", "discoverable-timeout", "0"])
        for prop in ("discoverable", "pairable"):
            res = _run(["bluetoothctl", prop, value])
            if "succeeded" not in res.stdout and res.returncode != 0:
                msg = (res.stderr or res.stdout).strip()
                return {"status": "error", "message": msg or f"{prop} {value} fehlgeschlagen"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Zeitüberschreitung"}

    logger.info("Bluetooth visibility: %s", value)
    return {"status": "ok", "discoverable": on}


def paired_devices() -> list[dict[str, str]]:
    """Devices bluez has paired — the only valid targets for sending."""
    if not available():
        return []
    try:
        res = _run(["bluetoothctl", "devices", "Paired"])
    except subprocess.TimeoutExpired:
        return []

    devices = []
    for line in res.stdout.splitlines():
        # "Device AA:BB:CC:DD:EE:FF Michaels iPhone"
        parts = line.strip().split(None, 2)
        if len(parts) >= 2 and parts[0] == "Device":
            devices.append({"address": parts[1], "name": parts[2] if len(parts) > 2 else parts[1]})
    return devices


def is_paired(address: str) -> bool:
    return any(d["address"].upper() == address.upper() for d in paired_devices())


# ── sending ───────────────────────────────────────────────────────────────────

def send_file(address: str, file_path: str) -> dict[str, Any]:
    """Push a file to a paired device over OBEX Object Push."""
    req = system_requirement()
    if req:
        return {"status": "error", "message": req}
    if not address:
        return {"status": "error", "message": "Keine Zieladresse angegeben"}
    if not Path(file_path).is_file():
        return {"status": "error", "message": f"Datei nicht gefunden: {file_path}"}

    # Guard the assertion crash described in the module docstring.
    if not is_paired(address):
        return {"status": "error",
                "message": f"Gerät {address} ist nicht gekoppelt — "
                           "zuerst über die Bluetooth-Seite koppeln"}

    try:
        res = _run(["bt-obex", "-p", address, file_path], timeout=_SEND_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Zeitüberschreitung beim Senden"}

    if res.returncode == 0:
        logger.info("Bluetooth sent %s to %s", file_path, address)
        return {"status": "ok", "address": address}

    msg = (res.stderr or res.stdout).strip()

    # obexftp speaks raw RFCOMM and sometimes succeeds where obexd refuses.
    if shutil.which("obexftp"):
        try:
            fb = _run(["obexftp", "-b", address, "-p", file_path], timeout=_SEND_TIMEOUT)
            if fb.returncode == 0:
                logger.info("Bluetooth sent %s to %s (obexftp)", file_path, address)
                return {"status": "ok", "address": address, "via": "obexftp"}
        except subprocess.TimeoutExpired:
            pass

    logger.warning("Bluetooth send failed (%s): %s", address, msg)
    return {"status": "error", "message": msg or "Senden fehlgeschlagen"}


# ── receiving ─────────────────────────────────────────────────────────────────

def receive_dir(config: dict[str, Any] | None = None) -> Path:
    configured = (config or {}).get("receive_dir") or ""
    return Path(configured) if configured else DEFAULT_RECEIVE_DIR


def _unit_active(unit: str) -> bool:
    try:
        res = subprocess.run(["systemctl", "is-active", unit],
                             capture_output=True, text=True, timeout=10)
        return res.stdout.strip() == "active"
    except Exception:
        return False


def receiver_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Whether the box is currently able to accept incoming files."""
    req = system_requirement()
    if req:
        return {"available": False, "reason": req}

    directory = receive_dir(config)
    adapter = adapter_status()
    return {
        "available": True,
        "receiving": _unit_active(RECEIVER_UNIT),
        "agent_running": _unit_active(AGENT_UNIT),
        "discoverable": adapter.get("discoverable", False),
        "directory": str(directory),
        "file_count": len(list_received(config)),
        "unit": RECEIVER_UNIT,
    }


def list_received(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Files that phones have pushed to the box, newest first."""
    directory = receive_dir(config)
    if not directory.is_dir():
        return []
    files = []
    for entry in directory.iterdir():
        if not entry.is_file():
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        files.append({
            "name": entry.name,
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
        })
    return sorted(files, key=lambda f: f["mtime"], reverse=True)
