"""WiFi management via NetworkManager (nmcli).

Linux-only. Gracefully reports unavailable when nmcli is missing (e.g. on the
Windows dev machine) so the admin page can render without crashing.
"""

from __future__ import annotations

import logging
import os
import platform
import re
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
    # Manche Meldungen kommen vom NetworkManager-Dienst selbst und sind trotz
    # LC_ALL=C übersetzt ("Fehler: … Eigenschaft fehlt") — beides abfangen.
    if raw.lower().startswith("fehler:"):
        raw = raw[7:].strip()
    if raw.lower().startswith("error:"):  # die Oberfläche schreibt selbst "Fehler:" davor
        raw = raw[6:].strip()
    low = raw.lower()
    if ("not authorized" in low or "insufficient privileges" in low
            or "nicht autorisiert" in low or "keine berechtigung" in low):
        return ("Keine Berechtigung für die Netzwerksteuerung (polkit). "
                "Bitte 'sudo ./scripts/setup.sh' erneut ausführen — das legt "
                "die polkit-Regel für WLAN an.")
    if ("secrets were required" in low or "no secrets provided" in low
            or "geheimnisse" in low):
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


def _scan_security(ssid: str) -> str:
    """SECURITY column of ``ssid`` from the cached scan ('' if unknown/open)."""
    try:
        res = _run(["-t", "-f", "SSID,SECURITY", "device", "wifi", "list",
                    "--rescan", "no"], timeout=10)
    except Exception:
        return ""
    for line in res.stdout.splitlines():
        parts = _split_terse(line)
        if len(parts) >= 2 and parts[0] == ssid:
            return parts[1]
    return ""


def connect(ssid: str, password: str | None = None, hidden: bool = False) -> dict[str, Any]:
    """Connect to a network. Returns {status, message}.

    Früher ``nmcli device wifi connect … password …``. Das scheitert auf
    echten Boxen mit "802-11-wireless-security.key-mgmt: property missing",
    sobald schon ein Profil gleichen Namens existiert oder das Netz nicht im
    Scan-Cache des gewählten Adapters steht. Daher derselbe Weg wie bei
    „Netz hinzufügen“: Profil explizit anlegen (bzw. vorhandenes nutzen) und
    dann ``connection up``.
    """
    if not nmcli_available():
        return {"status": "error", "message": "nmcli nicht verfügbar"}
    err = _validate_ssid(ssid)
    if err:
        return {"status": "error", "message": err}

    existing = [n for n in list_saved().get("networks", []) if n["ssid"] == ssid]
    if existing and not password:
        # Bekanntes Netz ohne neues Passwort → gespeichertes Profil verwenden
        return connect_saved(existing[0]["uuid"])

    # Reines WPA3-Netz braucht SAE statt WPA-PSK
    sec = _scan_security(ssid) if password else ""
    key_mgmt = "sae" if ("WPA3" in sec and "WPA2" not in sec and "WPA1" not in sec) else "wpa-psk"

    added = add_saved(ssid, password, hidden, key_mgmt=key_mgmt)
    if added.get("status") != "ok":
        return added
    result = connect_saved(added["uuid"])
    if result.get("status") != "ok" and not existing:
        # Neu angelegtes Profil, das nicht funktioniert (z. B. falsches
        # Passwort), nicht liegen lassen — sonst versucht NM es endlos.
        try:
            _run(["connection", "delete", "uuid", added["uuid"]], timeout=20)
        except Exception:
            pass
    return result


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


# ── Gespeicherte Netze (Verbindungsprofile) ──────────────────────────────────
#
# Eine Box wandert zwischen Heim-WLAN, Event-Location und Handy-Hotspot. Statt
# vor Ort jedes Mal neu zu verbinden, hinterlegt man alle Netze vorab;
# NetworkManager verbindet sich dann selbst mit dem verfügbaren Netz der
# höchsten Priorität (connection.autoconnect-priority).

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_PRIO_MIN, _PRIO_MAX = -999, 999  # Wertebereich von NetworkManager


def _unescape_terse(value: str) -> str:
    """Undo nmcli's ``-t``/``-g`` escaping (``\\:`` → ``:``, ``\\\\`` → ``\\``)."""
    return "".join(_split_terse(value)) if "\\" in value else value


def _validate_uuid(uuid: str) -> str | None:
    if not isinstance(uuid, str) or not _UUID_RE.match(uuid):
        return "Ungültige Verbindungs-ID."
    return None


def _validate_ssid(ssid: str) -> str | None:
    if not isinstance(ssid, str) or not ssid:
        return "Bitte einen Netzwerknamen (SSID) angeben."
    n = len(ssid.encode("utf-8"))
    if n > 32:
        return f"Der Netzwerkname ist zu lang ({n} Byte, erlaubt sind höchstens 32)."
    if any(ord(c) < 32 for c in ssid):
        return "Der Netzwerkname enthält ungültige Steuerzeichen."
    return None


def _validate_psk(psk: str) -> str | None:
    if not isinstance(psk, str):
        return "Ungültiges Passwort."
    if _HEX64_RE.match(psk):  # Roh-Schlüssel als 64 Hex-Zeichen ist auch erlaubt
        return None
    if not 8 <= len(psk) <= 63:
        return "Das WLAN-Passwort muss 8 bis 63 Zeichen lang sein."
    if any(not (32 <= ord(c) <= 126) for c in psk):
        return ("Das WLAN-Passwort darf nur normale Zeichen enthalten "
                "(keine Umlaute oder Sonderzeichen außerhalb von ASCII).")
    return None


def _scrub(text: str, secret: str | None) -> str:
    """Remove the password from nmcli output before it goes anywhere."""
    if secret:
        text = text.replace(secret, "***")
    return text


def _connection_ssid(uuid: str) -> str:
    try:
        res = _run(["-g", "802-11-wireless.ssid", "connection", "show", uuid], timeout=10)
    except Exception:
        return ""
    if res.returncode != 0:
        return ""
    return _unescape_terse(res.stdout.rstrip("\n"))


def parse_saved_connections(output: str) -> list[dict[str, Any]]:
    """Parse ``nmcli -t -f NAME,UUID,TYPE,AUTOCONNECT,AUTOCONNECT-PRIORITY,
    ACTIVE,DEVICE connection show`` and keep only WiFi profiles (no SSID yet)."""
    result = []
    for line in output.splitlines():
        parts = _split_terse(line)
        if len(parts) < 7:
            continue
        name, uuid, ctype, autoconnect, prio, active, device = parts[:7]
        if ctype not in ("802-11-wireless", "wifi"):
            continue
        try:
            priority = int(prio)
        except ValueError:
            priority = 0
        result.append({
            "name": name,
            "uuid": uuid,
            "autoconnect": autoconnect == "yes",
            "priority": priority,
            "active": active == "yes",
            "device": device if device and device != "--" else None,
        })
    return result


def list_saved() -> dict[str, Any]:
    """All saved WiFi profiles, highest priority first, with their SSID."""
    if not nmcli_available():
        return {"available": False, "networks": [],
                "message": "NetworkManager (nmcli) ist auf diesem System nicht verfügbar."}
    try:
        res = _run(["-t", "-f", "NAME,UUID,TYPE,AUTOCONNECT,AUTOCONNECT-PRIORITY,ACTIVE,DEVICE",
                    "connection", "show"], timeout=15)
    except subprocess.TimeoutExpired:
        return {"available": True, "networks": [],
                "message": "Zeitüberschreitung beim Abfragen der gespeicherten Netze."}
    if res.returncode != 0:
        return {"available": True, "networks": [],
                "message": _friendly_error((res.stderr or res.stdout).strip())}

    networks = parse_saved_connections(res.stdout)
    for net in networks:
        net["ssid"] = _connection_ssid(net["uuid"]) or net["name"]
    networks.sort(key=lambda n: (-n["priority"], n["ssid"].lower()))
    return {"available": True, "networks": networks}


def _saved_wifi(uuid: str) -> dict[str, Any] | None:
    """The saved WiFi profile with this UUID, or None (also for non-WiFi)."""
    for net in list_saved().get("networks", []):
        if net["uuid"].lower() == uuid.lower():
            return net
    return None


def _simple_result(res: subprocess.CompletedProcess, secret: str | None = None,
                   fallback: str = "Aktion fehlgeschlagen") -> dict[str, Any]:
    if res.returncode == 0:
        return {"status": "ok"}
    msg = _scrub((res.stderr or res.stdout).strip(), secret)
    return {"status": "error", "message": _friendly_error(msg) or fallback}


def add_saved(ssid: str, password: str | None = None, hidden: bool = False,
              priority: int | None = None, key_mgmt: str = "wpa-psk") -> dict[str, Any]:
    """Save a network WITHOUT connecting — it need not be in range.

    An existing profile for the same SSID is replaced (e.g. new password); its
    priority is kept unless a new one is given. The new profile is created
    first, so a failure leaves the old one untouched.
    """
    if not nmcli_available():
        return {"status": "error", "message": "nmcli nicht verfügbar"}
    err = _validate_ssid(ssid)
    if err:
        return {"status": "error", "message": err}
    if password:
        err = _validate_psk(password)
        if err:
            return {"status": "error", "message": err}
    if priority is not None:
        try:
            priority = int(priority)
        except (TypeError, ValueError):
            return {"status": "error", "message": "Ungültige Priorität."}
        if not _PRIO_MIN <= priority <= _PRIO_MAX:
            return {"status": "error",
                    "message": f"Priorität muss zwischen {_PRIO_MIN} und {_PRIO_MAX} liegen."}

    existing = [n for n in list_saved().get("networks", []) if n["ssid"] == ssid]
    if priority is None:
        priority = max((n["priority"] for n in existing), default=0)

    args = ["connection", "add", "type", "wifi", "con-name", ssid, "ssid", ssid,
            "connection.autoconnect", "yes",
            "connection.autoconnect-priority", str(priority)]
    if hidden:
        args += ["802-11-wireless.hidden", "yes"]
    if password:
        if key_mgmt not in ("wpa-psk", "sae"):
            key_mgmt = "wpa-psk"
        args += ["wifi-sec.key-mgmt", key_mgmt, "wifi-sec.psk", password]
    try:
        res = _run(args, timeout=20)
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Zeitüberschreitung beim Speichern"}
    if res.returncode != 0:
        msg = _scrub((res.stderr or res.stdout).strip(), password)
        logger.warning("WiFi profile add failed (%s): %s", ssid, msg)
        return {"status": "error", "message": _friendly_error(msg) or "Speichern fehlgeschlagen"}

    # "Connection 'X' (<uuid>) successfully added."
    m = re.search(r"\(([0-9a-fA-F-]{36})\)", res.stdout)
    new_uuid = m.group(1) if m else None
    for old in existing:
        if old["uuid"] == new_uuid:
            continue
        try:
            _run(["connection", "delete", "uuid", old["uuid"]], timeout=20)
        except Exception:
            logger.warning("could not delete old WiFi profile %s", old["uuid"])
    logger.info("WiFi profile saved: %s (priority %s, replaced %d)", ssid, priority, len(existing))
    if not new_uuid:  # Ausgabe unerwartet — Profil über die SSID wiederfinden
        fresh = [n for n in list_saved().get("networks", []) if n["ssid"] == ssid]
        new_uuid = fresh[0]["uuid"] if fresh else None
    return {"status": "ok", "ssid": ssid, "uuid": new_uuid, "replaced": len(existing) > 0}


def delete_saved(uuid: str) -> dict[str, Any]:
    if not nmcli_available():
        return {"status": "error", "message": "nmcli nicht verfügbar"}
    err = _validate_uuid(uuid)
    if err:
        return {"status": "error", "message": err}
    if not _saved_wifi(uuid):
        return {"status": "error", "message": "Dieses WLAN-Profil gibt es nicht (mehr)."}
    try:
        res = _run(["connection", "delete", "uuid", uuid], timeout=20)
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Zeitüberschreitung"}
    return _simple_result(res, fallback="Entfernen fehlgeschlagen")


def set_priority(uuid: str, priority: int) -> dict[str, Any]:
    if not nmcli_available():
        return {"status": "error", "message": "nmcli nicht verfügbar"}
    err = _validate_uuid(uuid)
    if err:
        return {"status": "error", "message": err}
    try:
        priority = int(priority)
    except (TypeError, ValueError):
        return {"status": "error", "message": "Ungültige Priorität."}
    if not _PRIO_MIN <= priority <= _PRIO_MAX:
        return {"status": "error",
                "message": f"Priorität muss zwischen {_PRIO_MIN} und {_PRIO_MAX} liegen."}
    if not _saved_wifi(uuid):
        return {"status": "error", "message": "Dieses WLAN-Profil gibt es nicht (mehr)."}
    try:
        res = _run(["connection", "modify", "uuid", uuid,
                    "connection.autoconnect-priority", str(priority)], timeout=20)
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Zeitüberschreitung"}
    return _simple_result(res, fallback="Priorität konnte nicht gesetzt werden")


def connect_saved(uuid: str) -> dict[str, Any]:
    """Activate a saved profile now, on the adapter that actually sees it."""
    if not nmcli_available():
        return {"status": "error", "message": "nmcli nicht verfügbar"}
    err = _validate_uuid(uuid)
    if err:
        return {"status": "error", "message": err}
    net = _saved_wifi(uuid)
    if not net:
        return {"status": "error", "message": "Dieses WLAN-Profil gibt es nicht (mehr)."}
    ssid = net["ssid"]

    def attempt(ifname: str | None) -> subprocess.CompletedProcess:
        args = ["connection", "up", "uuid", uuid]
        if ifname:
            args += ["ifname", ifname]
        return _run(args, timeout=45)

    try:
        seen = _devices_seeing(ssid)
        if not seen:
            seen = _rescan_for(ssid)
        res = attempt(seen[0] if seen else None)
        # Profil ggf. an einen anderen Adapter gebunden → NM selbst wählen lassen
        if res.returncode != 0 and seen:
            low = (res.stderr + res.stdout).lower()
            if "secrets" not in low and "not authorized" not in low:
                res = attempt(None)
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Zeitüberschreitung beim Verbinden"}

    if res.returncode == 0:
        logger.info("WiFi connected via saved profile: %s", ssid)
        return {"status": "ok", "ssid": ssid}
    msg = (res.stderr or res.stdout).strip()
    logger.warning("WiFi connect (saved %s) failed: %s", ssid, msg)
    low = msg.lower()
    if not seen and ("no suitable device" in low or "no network" in low
                     or "not available" in low):
        return {"status": "error",
                "message": f"„{ssid}“ ist gerade nicht in Reichweite."}
    return {"status": "error", "message": _friendly_error(msg) or "Verbindung fehlgeschlagen"}
