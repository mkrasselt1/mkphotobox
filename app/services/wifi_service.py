"""WiFi management via NetworkManager (nmcli).

Linux-only. Gracefully reports unavailable when nmcli is missing (e.g. on the
Windows dev machine) so the admin page can render without crashing.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import time
from typing import Any

logger = logging.getLogger(__name__)

_TIMEOUT = 25  # nmcli scan/connect can take a while


def nmcli_available() -> bool:
    """True if nmcli is present (NetworkManager is in use)."""
    return platform.system() == "Linux" and shutil.which("nmcli") is not None


def _run(args: list[str], timeout: int = _TIMEOUT) -> subprocess.CompletedProcess:
    # Englische Ausgabe erzwingen: auf einer deutschen Box sagt nmcli sonst
    # "aktiviert" statt "enabled" und "Fehler: …" statt "Error: …" — beides
    # werten wir hier aus.
    return subprocess.run(
        ["nmcli", *args],
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "LC_ALL": "C"},
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


def _friendly_error(raw: str) -> str:
    """Turn nmcli's error text into something an operator can act on.

    The common one on a booth: the app runs as a systemd service without an
    active login session, so polkit refuses every write action ("Not authorized
    to control networking"). Scanning needs no auth, which is why the network
    list looks fine right up until Verbinden.
    """
    raw = raw.strip()
    if raw.lower().startswith("error:"):  # die Oberfläche schreibt selbst "Fehler:" davor
        raw = raw[6:].strip()
    low = raw.lower()
    if "not authorized" in low or "insufficient privileges" in low:
        return ("Keine Berechtigung für die Netzwerksteuerung (polkit). "
                "Bitte 'sudo ./scripts/setup.sh' erneut ausführen — das legt "
                "die polkit-Regel für WLAN an.")
    if "secrets were required" in low or "no secrets provided" in low:
        return "Falsches WLAN-Passwort."
    if "no network with ssid" in low:
        return ("Das Netz ist gerade nicht in Reichweite des WLAN-Adapters. "
                "Näher an den Router, oder 'Neu suchen' und noch einmal verbinden.")
    return raw


def _wifi_devices() -> list[tuple[str, str]]:
    """(device, state) of every WiFi adapter, connected ones first.

    Boxes end up with more than one adapter (onboard plus a USB stick bought
    for better range). Taking simply the first one showed "Nicht verbunden"
    while the other adapter was online.
    """
    try:
        res = _run(["-t", "-f", "DEVICE,TYPE,STATE", "device", "status"], timeout=10)
    except Exception:
        return []
    devs = []
    for line in res.stdout.splitlines():
        parts = _split_terse(line)
        if len(parts) >= 3 and parts[1] == "wifi":
            devs.append((parts[0], parts[2]))
    return sorted(devs, key=lambda d: d[1] != "connected")


def _wifi_device() -> str | None:
    """The WiFi adapter to report on: a connected one, else the first."""
    devs = _wifi_devices()
    return devs[0][0] if devs else None


def _devices_seeing(ssid: str) -> list[str]:
    """WiFi adapters whose last scan contains ``ssid``, strongest first."""
    try:
        res = _run(["-t", "-f", "DEVICE,SSID,SIGNAL", "device", "wifi", "list",
                    "--rescan", "no"], timeout=10)
    except Exception:
        return []
    best: dict[str, int] = {}
    for line in res.stdout.splitlines():
        parts = _split_terse(line)
        if len(parts) >= 3 and parts[1] == ssid:
            sig = int(parts[2]) if parts[2].isdigit() else 0
            best[parts[0]] = max(sig, best.get(parts[0], -1))
    return sorted(best, key=best.get, reverse=True)


def _rescan_for(ssid: str, wait: float = 8.0) -> list[str]:
    """Targeted rescan for one SSID on every adapter; wait until one sees it.

    Some USB drivers age scan results out within seconds — the list on screen
    still shows the network, but by the time Verbinden is pressed NetworkManager
    has forgotten it and answers "No network with SSID … found".
    """
    for dev, _state in _wifi_devices():
        try:
            _run(["device", "wifi", "rescan", "ifname", dev, "ssid", ssid], timeout=15)
        except Exception:
            pass
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        seen = _devices_seeing(ssid)
        if seen:
            return seen
        time.sleep(1)
    return []


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

    def attempt(ifname: str | None) -> subprocess.CompletedProcess:
        args = ["device", "wifi", "connect", ssid]
        if password:
            args += ["password", password]
        if hidden:
            args += ["hidden", "yes"]
        # Ohne ifname nimmt nmcli irgendeinen Adapter — bei zwei Adaptern
        # auch den, der das Netz gar nicht sieht.
        if ifname:
            args += ["ifname", ifname]
        return _run(args, timeout=45)

    try:
        seen = [] if hidden else _devices_seeing(ssid)
        res = attempt(seen[0] if seen else None)
        if (res.returncode != 0 and not hidden
                and "no network with ssid" in (res.stderr + res.stdout).lower()):
            seen = _rescan_for(ssid)
            if seen:
                res = attempt(seen[0])
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Zeitüberschreitung beim Verbinden"}

    if res.returncode == 0:
        logger.info("WiFi connected: %s", ssid)
        return {"status": "ok", "ssid": ssid, "message": res.stdout.strip()}
    msg = (res.stderr or res.stdout).strip()
    logger.warning("WiFi connect failed (%s): %s", ssid, msg)
    return {"status": "error", "message": _friendly_error(msg) or "Verbindung fehlgeschlagen"}


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
    return {"status": "error", "message": _friendly_error((res.stderr or res.stdout).strip())}


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
    return {"status": "error", "message": _friendly_error((res.stderr or res.stdout).strip())}


def set_radio(on: bool) -> dict[str, Any]:
    if not nmcli_available():
        return {"status": "error", "message": "nmcli nicht verfügbar"}
    try:
        res = _run(["radio", "wifi", "on" if on else "off"], timeout=10)
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Zeitüberschreitung"}
    if res.returncode == 0:
        return {"status": "ok", "radio_enabled": on}
    return {"status": "error", "message": _friendly_error((res.stderr or res.stdout).strip())}
