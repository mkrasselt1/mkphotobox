"""Drucker einrichten, ohne dass jemand CUPS kennen muss.

Sucht angeschlossene und im Netz sichtbare Drucker (``lpinfo -v``), wählt
einen Treiber und legt die Warteschlange per ``lpadmin`` an:

* Netzwerk-/IPP-Drucker und USB-Drucker hinter ``ipp-usb``: treiberlos
  (``-m everywhere``) — das können praktisch alle Drucker ab ca. 2015.
* Klassische USB-Drucker und Thermosublimationsdrucker (Canon SELPHY, DNP,
  Mitsubishi, Kodak, …): Treiber über die Geräte-ID aus ``lpinfo -m``,
  bevorzugt Gutenprint mit dessen eigenem USB-Backend.

Nicht jeder Drucker lässt sich so einrichten; dann meldet ``add_printer``
einen Fehler im Klartext und die CUPS-Weboberfläche bleibt der Ausweg.

Rechte: der Dienstbenutzer muss in der Gruppe ``lpadmin`` sein (setup.sh),
dann klappt lpadmin über den lokalen CUPS-Socket ohne Passwort.

Kommandozeile (setup.sh ruft das am Ende auf)::

    python -m app.services.printer_setup auto     # USB-Drucker einrichten
    python -m app.services.printer_setup list     # gefundene Geräte zeigen
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

logger = logging.getLogger(__name__)

# lpinfo/lpstat übersetzen ihre Ausgabe — geparst wird nur die englische.
_ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}

# Schemes, die lpinfo als leere „Vorlage“ auflistet (uri = "ipp", "socket", …)
# oder die nichts mit einem echten Gerät zu tun haben.
_SKIP_SCHEMES = {"implicitclass", "cups-pdf", "cups-brf", "beh", "driverless-fax",
                 "fax", "serial", "parallel"}


def _run(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=_ENV)


def is_supported() -> bool:
    return sys.platform.startswith("linux") and bool(shutil.which("lpadmin"))


# ── Geräte finden ─────────────────────────────────────────────────────────

def _parse_lpinfo_devices(text: str) -> list[dict[str, str]]:
    devices, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^Device:\s*uri\s*=\s*(.*)$", line.strip())
        if m:
            cur = {"uri": m.group(1).strip()}
            devices.append(cur)
            continue
        m = re.match(r"^\s*([a-z-]+)\s*=\s*(.*)$", line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2).strip()
    return devices


def _scheme(uri: str) -> str:
    return uri.split(":", 1)[0].lower()


def _connection(uri: str) -> str:
    """usb / network — für die Anzeige und für die Auto-Einrichtung."""
    s = _scheme(uri)
    if "usb" in s:
        return "usb"
    # ipp-usb stellt USB-Drucker als IPP-Dienst auf localhost bereit.
    host = (urlparse(uri).hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1"):
        return "usb"
    return "network"


def _is_ipp(uri: str) -> bool:
    s = _scheme(uri)
    if s in ("ipp", "ipps"):
        return True
    if s == "dnssd":
        return "._ipp" in unquote(uri) or "._ipps" in unquote(uri)
    return False


def _serial(dev: dict[str, str]) -> str:
    uri = dev["uri"]
    q = parse_qs(urlparse(uri).query)
    if q.get("serial"):
        return q["serial"][0].lower()
    if _scheme(uri).startswith("gutenprint"):           # gutenprint53+usb://modell/SERIAL
        tail = urlparse(uri).path.strip("/")
        if tail:
            return unquote(tail).lower()
    m = re.search(r"(?:SN|SERN|SERIALNUMBER):([^;]+)", dev.get("device-id", ""), re.I)
    return m.group(1).strip().lower() if m else ""


def _norm_model(dev: dict[str, str]) -> str:
    mm = dev.get("make-and-model") or dev.get("info") or ""
    return re.sub(r"[^a-z0-9]", "", mm.lower())


def configured_printers() -> list[dict[str, str]]:
    """Bereits angelegte Warteschlangen mit ihrer Geräte-URI."""
    try:
        r = _run(["lpstat", "-v"], timeout=10)
    except Exception:
        return []
    out = []
    for line in r.stdout.splitlines():
        m = re.match(r"^device for (\S+):\s*(.*)$", line.strip())
        if m:
            out.append({"name": m.group(1), "uri": m.group(2).strip()})
    return out


def discover(timeout: int = 8) -> list[dict[str, Any]]:
    """Alle Drucker, die CUPS gerade sieht — dedupliziert und mit Hinweis,
    ob sie schon eingerichtet sind."""
    try:
        r = _run(["lpinfo", "-l", "-v", "--timeout", str(timeout)], timeout=timeout + 20)
    except subprocess.TimeoutExpired:
        return []
    raw = [d for d in _parse_lpinfo_devices(r.stdout)
           if "://" in d["uri"] and _scheme(d["uri"]) not in _SKIP_SCHEMES
           and d.get("class") in ("direct", "network", None)]

    # Dasselbe Gerät taucht oft mehrfach auf (usb:// + gutenprint53+usb://,
    # dnssd:// + ipp://). Pro Gerät die beste URI behalten.
    def rank(d: dict[str, str]) -> int:
        s = _scheme(d["uri"])
        if s.startswith("gutenprint"):
            return 0            # Thermosublimation braucht Gutenprints Backend
        if s == "dnssd" and _is_ipp(d["uri"]):
            return 1            # bleibt gültig, wenn sich die IP ändert
        if s in ("ipp", "ipps"):
            return 2
        if s == "usb":
            return 3
        return 5

    best: dict[str, dict[str, str]] = {}
    for d in sorted(raw, key=rank):
        key = _serial(d) or _norm_model(d) or d["uri"]
        # Ohne Seriennummer nur über das Modell zusammenfassen, wenn es ein
        # Modell gibt — zwei unbekannte Netzwerkgeräte bleiben getrennt.
        if not _serial(d) and _norm_model(d) in ("", "unknown"):
            key = d["uri"]
        if key not in best:
            best[key] = d
        else:
            # Gleiches Modell an USB und im Netz sind zwei Geräte.
            if _connection(best[key]["uri"]) != _connection(d["uri"]):
                best[key + "|" + _connection(d["uri"])] = d

    queues = configured_printers()
    configured = {c["uri"]: c["name"] for c in queues}
    result = []
    for d in best.values():
        uri = d["uri"]
        name = d.get("make-and-model") or d.get("info") or uri
        if name.lower() == "unknown":
            name = d.get("info") or uri
        result.append({
            "uri": uri,
            "name": name,
            "info": d.get("info", ""),
            "device_id": d.get("device-id", ""),
            "connection": _connection(uri),
            "driverless": _is_ipp(uri),
            "configured_as": configured.get(uri),
        })
    # Schon eingerichtete Geräte (andere URI, gleiches Gerät) erkennen
    for item in result:
        if item["configured_as"]:
            continue
        for c in queues:
            if _same_device(item, c["uri"]):
                item["configured_as"] = c["name"]
                break
    result.sort(key=lambda x: (x["configured_as"] is not None, x["connection"] != "usb", x["name"].lower()))
    return result


def _same_device(item: dict[str, Any], uri: str) -> bool:
    other = {"uri": uri}
    s1, s2 = _serial({"uri": item["uri"], "device-id": item.get("device_id", "")}), _serial(other)
    return bool(s1 and s2 and s1 == s2)


# ── Treiber wählen ────────────────────────────────────────────────────────

def _list_drivers() -> list[tuple[str, str]]:
    """Alle installierten Treiber als (ppd-name, Beschreibung)."""
    try:
        r = _run(["lpinfo", "-m"], timeout=90)
    except subprocess.TimeoutExpired:
        return []
    out = []
    for ln in r.stdout.splitlines():
        if " " in ln.strip():
            name, desc = ln.strip().split(" ", 1)
            out.append((name, desc))
    return out


def _desc_model(desc: str) -> str:
    """'Mitsubishi CP-9550DW - CUPS+Gutenprint v5.3.4' -> 'Mitsubishi CP-9550DW'"""
    return re.split(r" - |, | Foomatic/| \(", desc, maxsplit=1)[0]


def _choose_driver(dev: dict[str, Any]) -> str | None:
    """Passenden Treiber wählen. ``lpinfo -m --device-id`` hilft dabei nicht:
    es filtert nicht, sondern liefert alle Treiber — der erste Treffer war
    z. B. für einen Mitsubishi CP9550 ein HP-Apollo-Tintenstrahler."""
    uri = dev["uri"]
    if _is_ipp(uri):
        return "everywhere"
    drivers = _list_drivers()
    if not drivers:
        return None

    # Gutenprints Backend steckt das genaue Modell in die URI
    # (gutenprint53+usb://mitsubishi-9550dw-s/SERIAL) — der Treiber heißt gleich.
    if _scheme(uri).startswith("gutenprint"):
        gp_model = (urlparse(uri).hostname or "").lower()
        for variant in ("expert", "simple"):
            for name, _ in drivers:
                if re.fullmatch(rf"gutenprint\.[\d.]+://{re.escape(gp_model)}/{variant}", name):
                    return name

    did = dev.get("device_id", "")
    mfg = re.search(r"(?:MFG|MANUFACTURER):([^;]+)", did, re.I)
    mdl = re.search(r"(?:MDL|MODEL):([^;]+)", did, re.I)
    mfg = mfg.group(1).strip() if mfg else ""
    mdl = mdl.group(1).strip() if mdl else ""
    if not mdl:
        # ohne Geräte-ID: Hersteller = erstes Wort von make-and-model
        mm = (dev.get("name") or "").strip()
        mfg, _, mdl = mm.partition(" ")
    norm = lambda t: re.sub(r"[^a-z0-9]", "", (t or "").lower())
    n_mfg, n_mdl = norm(mfg), norm(mdl)
    if not n_mdl:
        return None

    scored = []
    for name, desc in drivers:
        if name in ("raw", "everywhere") or "fax" in name.lower():
            continue
        dm = norm(_desc_model(desc))
        if dm in (n_mfg + n_mdl, n_mdl):
            score = 0                      # exakt dieses Modell
        elif dm.endswith(n_mdl) and (not n_mfg or dm.startswith(n_mfg[:4])):
            score = 1
        else:
            continue
        if "recommended" in desc.lower():
            score -= 0.5
        if name.startswith("gutenprint") and name.endswith("/expert"):
            score -= 0.2
        scored.append((score, name))
    if not scored:
        return None
    return min(scored)[1]


def _queue_name(dev: dict[str, Any]) -> str:
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", dev.get("name") or "Drucker").strip("_")[:40] or "Drucker"
    taken = {c["name"].lower() for c in configured_printers()}
    name, i = base, 2
    while name.lower() in taken:
        name, i = f"{base}_{i}", i + 1
    return name


def _default_printer() -> str:
    try:
        r = _run(["lpstat", "-d"], timeout=10)
    except Exception:
        return ""
    return r.stdout.split(":", 1)[1].strip() if "destination:" in r.stdout else ""


def _human_error(text: str) -> str:
    t = (text or "").strip()
    low = t.lower()
    if "forbidden" in low or "not authorized" in low or "unauthorized" in low:
        return ("Keine Berechtigung, Drucker anzulegen. Der Dienstbenutzer muss in der "
                "Gruppe 'lpadmin' sein — einmal 'sudo ./scripts/setup.sh' ausführen.")
    if "unable to connect" in low or "unable to get printer attributes" in low:
        return "Drucker antwortet nicht — eingeschaltet und im selben Netz?"
    return t or "Unbekannter Fehler"


# ── Einrichten / Entfernen ───────────────────────────────────────────────

def add_printer(uri: str, name: str = "", driver: str = "", make_default: bool | None = None,
                devices: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Warteschlange anlegen. Treiber wird automatisch gewählt, wenn keiner
    angegeben ist. ``make_default=None`` → Standard, falls es noch keinen gibt."""
    if not is_supported():
        return {"status": "error", "message": "Nur unter Linux mit CUPS möglich."}
    devices = discover() if devices is None else devices
    dev = next((d for d in devices if d["uri"] == uri), None) or {"uri": uri, "name": name or uri}
    if dev.get("configured_as"):
        return {"status": "ok", "printer": dev["configured_as"], "already": True}
    if name:
        dev["name"] = name
    model = driver or _choose_driver(dev)
    if not model:
        # Moderner USB-Drucker ohne PPD: ipp-usb macht ihn als IPP-Dienst
        # sichtbar — dann treiberlos über diesen Weg.
        twin = next((d for d in devices if d["driverless"] and d is not dev
                     and _norm_model({"make-and-model": d["name"]}) == _norm_model({"make-and-model": dev.get("name", "")})),
                    None)
        if twin:
            dev, uri, model = twin, twin["uri"], "everywhere"
    if not model:
        return {"status": "error", "message": (
            f"Für „{dev.get('name')}“ ist kein Treiber installiert. Fotodrucker brauchen meist "
            "das Paket printer-driver-gutenprint; andere Hersteller liefern eigene Linux-Treiber.")}
    queue = _queue_name(dev)
    args = ["lpadmin", "-p", queue, "-E", "-v", uri, "-m", model,
            "-o", "printer-error-policy=retry-job"]
    if dev.get("info"):
        args += ["-D", dev["info"]]
    try:
        r = _run(args, timeout=120)   # "everywhere" fragt den Drucker ab — kann dauern
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Zeitüberschreitung beim Einrichten — Drucker erreichbar?"}
    if r.returncode != 0:
        logger.warning("lpadmin %s failed: %s", queue, r.stderr.strip())
        return {"status": "error", "message": _human_error(r.stderr or r.stdout)}
    # -E vor -v aktiviert nur; sicherheitshalber annehmen + starten
    _run(["cupsaccept", queue], timeout=10)
    _run(["cupsenable", queue], timeout=10)
    if make_default or (make_default is None and not _default_printer()):
        _run(["lpadmin", "-d", queue], timeout=10)
    logger.info("Drucker eingerichtet: %s (%s, Treiber %s)", queue, uri, model)
    return {"status": "ok", "printer": queue, "driver": model, "uri": uri}


def remove_printer(queue: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+", queue or ""):
        return {"status": "error", "message": "Ungültiger Druckername"}
    r = _run(["lpadmin", "-x", queue], timeout=20)
    if r.returncode != 0:
        return {"status": "error", "message": _human_error(r.stderr or r.stdout)}
    return {"status": "ok"}


def auto_setup() -> dict[str, Any]:
    """Jeden angeschlossenen (USB-)Drucker einrichten, der noch fehlt.
    Netzwerkdrucker bewusst nicht: im Hotel-WLAN sähe man sonst fremde Drucker."""
    if not is_supported():
        return {"added": [], "failed": [], "skipped": "kein CUPS"}
    added, failed = [], []
    devices = discover()
    for dev in devices:
        if dev["connection"] != "usb" or dev["configured_as"]:
            continue
        res = add_printer(dev["uri"], devices=devices)
        if res.get("printer"):
            dev["configured_as"] = res["printer"]
        if res.get("status") == "ok":
            added.append({"name": dev["name"], "printer": res["printer"]})
        else:
            failed.append({"name": dev["name"], "message": res.get("message", "")})
    return {"added": added, "failed": failed}


def _main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cmd = argv[1] if len(argv) > 1 else "auto"
    if not is_supported():
        print("    CUPS (lpadmin) nicht gefunden — übersprungen")
        return 0
    if cmd == "list":
        for d in discover():
            state = f"eingerichtet als {d['configured_as']}" if d["configured_as"] else "neu"
            print(f"    [{d['connection']:7}] {d['name']}  ({state})\n              {d['uri']}")
        return 0
    res = auto_setup()
    for a in res["added"]:
        print(f"    eingerichtet: {a['name']} -> {a['printer']}")
    for f in res["failed"]:
        print(f"    !! {f['name']}: {f['message']}")
    if not res["added"] and not res["failed"]:
        print("    kein neuer USB-Drucker gefunden")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
