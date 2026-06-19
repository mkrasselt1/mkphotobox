"""WiFi management via NetworkManager (nmcli).

Linux-only. Gracefully reports unavailable when nmcli is missing (e.g. on the
Windows dev machine) so the admin page can render without crashing.
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

_TIMEOUT = 25  # nmcli scan/connect can take a while


def nmcli_available() -> bool:
    """True if nmcli is present (NetworkManager is in use)."""
    return platform.system() == "Linux" and shutil.which("nmcli") is not None


def _run(args: list[str], timeout: int = _TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["nmcli", *args],
        capture_output=True, text=True, timeout=timeout,
    )


def _split_terse(line: str) -> list[str]:
    """Split an nmcli terse (-t) line on unescaped colons.

    nmcli escapes literal colons inside a field as ``\\:`` — e.g. SSIDs or
    MAC addresses. A naive ``line.split(":")`` would mangle those.
    """
    fields: list[str] = []
    current = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            current.append(line[i + 1])
            i += 2
            continue
        if ch == ":":
            fields.append("".join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    fields.append("".join(current))
    return fields


def _wifi_device() -> str | None:
    """Return the name of the first WiFi device, or None."""
    try:
        res = _run(["-t", "-f", "DEVICE,TYPE", "device", "status"], timeout=10)
    except Exception:
        return None
    for line in res.stdout.splitlines():
        parts = _split_terse(line)
        if len(parts) >= 2 and parts[1] == "wifi":
            return parts[0]
    return None


def radio_enabled() -> bool:
    try:
        res = _run(["radio", "wifi"], timeout=10)
        return res.stdout.strip().lower() == "enabled"
    except Exception:
        return False


def get_status() -> dict[str, Any]:
    """Current WiFi state: availability, radio, active connection, IP."""
    if not nmcli_available():
        return {
            "available": False,
            "reason": "NetworkManager (nmcli) ist auf diesem System nicht verfügbar.",
        }

    device = _wifi_device()
    status: dict[str, Any] = {
        "available": True,
        "device": device,
        "radio_enabled": radio_enabled(),
        "connected": False,
        "ssid": None,
        "ip": None,
        "signal": None,
    }
    if not device:
        status["reason"] = "Kein WLAN-Adapter gefunden."
        return status

    try:
        res = _run(
            ["-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS",
             "device", "show", device],
            timeout=10,
        )
        for line in res.stdout.splitlines():
            parts = _split_terse(line)
            if len(parts) < 2:
                continue
            key, value = parts[0], parts[1]
            if key == "GENERAL.CONNECTION" and value and value != "--":
                status["ssid"] = value
                status["connected"] = True
            elif key == "IP4.ADDRESS[1]":
                status["ip"] = value.split("/")[0]
    except Exception:
        logger.exception("wifi status query failed")

    # Signal strength of the active network
    if status["connected"]:
        try:
            res = _run(["-t", "-f", "ACTIVE,SIGNAL", "device", "wifi", "list",
                        "--rescan", "no"], timeout=10)
            for line in res.stdout.splitlines():
                parts = _split_terse(line)
                if len(parts) >= 2 and parts[0] == "yes":
                    status["signal"] = int(parts[1]) if parts[1].isdigit() else None
                    break
        except Exception:
            pass

    return status


def scan_networks(rescan: bool = True) -> list[dict[str, Any]]:
    """List visible WiFi networks, strongest first, deduplicated by SSID."""
    if not nmcli_available():
        return []
    args = ["-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
            "--rescan", "yes" if rescan else "no"]
    try:
        res = _run(args)
    except subprocess.TimeoutExpired:
        # Rescan can time out on busy radios — fall back to cached results
        res = _run(["-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY", "device", "wifi",
                    "list", "--rescan", "no"], timeout=10)

    seen: dict[str, dict[str, Any]] = {}
    for line in res.stdout.splitlines():
        parts = _split_terse(line)
        if len(parts) < 4:
            continue
        active, ssid, signal, security = parts[0], parts[1], parts[2], parts[3]
        if not ssid:  # hidden network — skip in list
            continue
        entry = {
            "ssid": ssid,
            "signal": int(signal) if signal.isdigit() else 0,
            "security": security or "Offen",
            "active": active == "yes",
            "secured": bool(security and security != ""),
        }
        # Keep the strongest sighting of each SSID
        prev = seen.get(ssid)
        if prev is None or entry["signal"] > prev["signal"]:
            seen[ssid] = entry

    return sorted(seen.values(), key=lambda n: n["signal"], reverse=True)


def connect(ssid: str, password: str | None = None, hidden: bool = False) -> dict[str, Any]:
    """Connect to a network. Returns {status, message}."""
    if not nmcli_available():
        return {"status": "error", "message": "nmcli nicht verfügbar"}
    if not ssid:
        return {"status": "error", "message": "Kein SSID angegeben"}

    args = ["device", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    if hidden:
        args += ["hidden", "yes"]

    try:
        res = _run(args, timeout=45)
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Zeitüberschreitung beim Verbinden"}

    if res.returncode == 0:
        logger.info("WiFi connected: %s", ssid)
        return {"status": "ok", "ssid": ssid, "message": res.stdout.strip()}
    msg = (res.stderr or res.stdout).strip()
    logger.warning("WiFi connect failed (%s): %s", ssid, msg)
    return {"status": "error", "message": msg or "Verbindung fehlgeschlagen"}


def disconnect() -> dict[str, Any]:
    if not nmcli_available():
        return {"status": "error", "message": "nmcli nicht verfügbar"}
    device = _wifi_device()
    if not device:
        return {"status": "error", "message": "Kein WLAN-Adapter gefunden"}
    try:
        res = _run(["device", "disconnect", device], timeout=20)
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Zeitüberschreitung"}
    if res.returncode == 0:
        return {"status": "ok"}
    return {"status": "error", "message": (res.stderr or res.stdout).strip()}


def forget(ssid: str) -> dict[str, Any]:
    """Delete a saved connection profile."""
    if not nmcli_available():
        return {"status": "error", "message": "nmcli nicht verfügbar"}
    try:
        res = _run(["connection", "delete", "id", ssid], timeout=20)
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Zeitüberschreitung"}
    if res.returncode == 0:
        return {"status": "ok"}
    return {"status": "error", "message": (res.stderr or res.stdout).strip()}


def set_radio(on: bool) -> dict[str, Any]:
    if not nmcli_available():
        return {"status": "error", "message": "nmcli nicht verfügbar"}
    try:
        res = _run(["radio", "wifi", "on" if on else "off"], timeout=10)
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Zeitüberschreitung"}
    if res.returncode == 0:
        return {"status": "ok", "radio_enabled": on}
    return {"status": "error", "message": (res.stderr or res.stdout).strip()}
