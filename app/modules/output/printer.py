"""Printer output — server-side printing via CUPS (Linux) or Windows.

Supports configurable printer, paper size, copies, orientation, margins.
Also provides a "browser print" mode where the client opens the print dialog.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import subprocess
from pathlib import Path
from typing import Any

from app.modules.output.base import AbstractOutput

logger = logging.getLogger(__name__)


class PrinterOutput(AbstractOutput):
    name = "output.printer"

    def __init__(self):
        self._printer_name = ""
        self._paper_size = "4x6"
        self._copies = 1
        self._orientation = "portrait"
        self._mode = "browser"
        self._fit_to_page = True
        self._margin_mm = 0

    async def initialize(self, config: dict[str, Any]) -> None:
        self._printer_name = config.get("printer_name", "")
        self._paper_size = config.get("paper_size", "4x6")
        self._copies = config.get("copies", 1)
        self._orientation = config.get("orientation", "portrait")
        self._mode = config.get("mode", "browser")
        self._fit_to_page = config.get("fit_to_page", True)
        self._margin_mm = config.get("margin_mm", 0)

    async def shutdown(self) -> None:
        pass

    def is_available(self) -> bool:
        if self._mode == "browser":
            return True
        system = platform.system()
        if system == "Linux":
            try:
                import cups  # noqa: F401
                return True
            except ImportError:
                return False
        elif system == "Windows":
            return True
        return False

    # Per-job overrides a caller may pass via metadata (e.g. a template's print
    # preset → route the 3-photo strip to the panorama printer).
    _OVERRIDE_KEYS = ("printer_name", "paper_size", "copies", "orientation",
                      "margin_mm", "fit_to_page", "mode")

    async def send(self, photo_path: str, metadata: dict[str, Any]) -> dict[str, Any]:
        override = {k: metadata[k] for k in self._OVERRIDE_KEYS if metadata.get(k) is not None}
        mode = override.get("mode", self._mode)
        if mode == "browser":
            return {"status": "ok", "print_mode": "browser"}
        return await asyncio.to_thread(self._print_sync, photo_path, override)

    def _print_sync(self, photo_path: str, override: dict[str, Any] | None = None) -> dict[str, Any]:
        photo = Path(photo_path)
        if not photo.exists():
            return {"status": "error", "message": "Photo file not found"}

        # Apply per-job overrides on top of the configured defaults, restoring
        # them afterwards so the override never leaks into later jobs.
        saved = {k: getattr(self, f"_{k}") for k in self._OVERRIDE_KEYS if k != "mode"}
        for k, v in (override or {}).items():
            if k != "mode" and hasattr(self, f"_{k}"):
                setattr(self, f"_{k}", v)

        system = platform.system()
        try:
            if system == "Linux":
                return self._print_cups(photo)
            elif system == "Windows":
                return self._print_windows(photo)
            else:
                return {"status": "error", "message": f"Not supported on {system}"}
        except Exception as e:
            logger.exception("Print failed")
            return {"status": "error", "message": str(e)}
        finally:
            for k, v in saved.items():
                setattr(self, f"_{k}", v)

    def _print_cups(self, photo: Path) -> dict[str, Any]:
        try:
            import cups
        except ImportError:
            return self._print_lp(photo)

        conn = cups.Connection()
        printers = conn.getPrinters()
        printer = self._printer_name or conn.getDefault() or next(iter(printers), None)
        if not printer:
            return {"status": "error", "message": "No printer found"}

        options = {
            "media": self._paper_size,
            "copies": str(self._copies),
            "orientation-requested": "3" if self._orientation == "portrait" else "4",
        }
        if self._fit_to_page:
            options["fit-to-page"] = "true"
        if self._margin_mm > 0:
            margin_pt = str(int(self._margin_mm * 2.83))
            for side in ("top", "bottom", "left", "right"):
                options[f"page-{side}"] = margin_pt

        job_id = conn.printFile(printer, str(photo), f"Photobox-{photo.stem}", options)
        logger.info("CUPS print job %d on %s", job_id, printer)
        return {"status": "ok", "print_mode": "server", "printer": printer, "job_id": job_id}

    def _print_lp(self, photo: Path) -> dict[str, Any]:
        """Print via the CUPS `lp` CLI (used when pycups isn't installed)."""
        args = ["lp"]
        if self._printer_name:
            args += ["-d", self._printer_name]
        args += ["-n", str(self._copies)]
        if self._paper_size:
            args += ["-o", f"media={self._paper_size}"]
        if self._fit_to_page:
            args += ["-o", "fit-to-page"]
        args.append(str(photo))
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            logger.info("lp print: %s", result.stdout.strip())
            return {"status": "ok", "print_mode": "server",
                    "printer": self._printer_name or "(Systemstandard)",
                    "output": result.stdout.strip()}
        return {"status": "error", "message": (result.stderr or result.stdout).strip()}

    def _print_windows(self, photo: Path) -> dict[str, Any]:
        printer = self._printer_name or self._get_default_printer_win()
        if not printer:
            return {"status": "error", "message": "No printer found"}

        ps_script = f"""
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Drawing.Printing
$img = [System.Drawing.Image]::FromFile('{photo.resolve()}')
$pd = New-Object System.Drawing.Printing.PrintDocument
$pd.PrinterSettings.PrinterName = '{printer}'
$pd.PrinterSettings.Copies = {self._copies}
$pd.DefaultPageSettings.Landscape = {'$true' if self._orientation == 'landscape' else '$false'}
$pd.DefaultPageSettings.Margins = New-Object System.Drawing.Printing.Margins({self._margin_mm},{self._margin_mm},{self._margin_mm},{self._margin_mm})
$pd.add_PrintPage({{
    param($sender, $e)
    $bounds = $e.MarginBounds
    $ratio = [Math]::Min($bounds.Width / $img.Width, $bounds.Height / $img.Height)
    $w = [int]($img.Width * $ratio)
    $h = [int]($img.Height * $ratio)
    $x = $bounds.X + ($bounds.Width - $w) / 2
    $y = $bounds.Y + ($bounds.Height - $h) / 2
    $e.Graphics.DrawImage($img, $x, $y, $w, $h)
}})
$pd.Print()
$img.Dispose()
$pd.Dispose()
"""
        result = subprocess.run(
            ["powershell.exe", "-Command", ps_script],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            logger.info("Windows print: %s on %s (%d copies)", photo.name, printer, self._copies)
            return {"status": "ok", "print_mode": "server", "printer": printer}
        logger.error("Print error: %s", result.stderr[:300])
        return {"status": "error", "message": result.stderr[:300]}

    @staticmethod
    def _get_default_printer_win() -> str:
        try:
            result = subprocess.run(
                ["powershell.exe", "-Command",
                 "(Get-CimInstance Win32_Printer | Where-Object {$_.Default}).Name"],
                capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    @staticmethod
    def list_printers() -> list[dict[str, str]]:
        """List available printers on the system."""
        system = platform.system()
        if system == "Windows":
            return PrinterOutput._list_printers_win()
        elif system == "Linux":
            return PrinterOutput._list_printers_cups()
        return []

    @staticmethod
    def _list_printers_win() -> list[dict[str, str]]:
        try:
            result = subprocess.run(
                ["powershell.exe", "-Command",
                 "Get-Printer | Select-Object Name, DriverName, @{N='Default';E={$_.IsDefault}} "
                 "| ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=10,
            )
            import json
            data = json.loads(result.stdout)
            if isinstance(data, dict):
                data = [data]
            return [{"name": p["Name"], "driver": p.get("DriverName", ""), "default": p.get("Default", False)} for p in data]
        except Exception:
            return []

    @staticmethod
    def list_paper_sizes(printer_name: str) -> dict[str, Any]:
        """Return supported paper sizes for a printer (+ the default)."""
        system = platform.system()
        if system == "Linux":
            return PrinterOutput._paper_sizes_cups(printer_name)
        if system == "Windows":
            return PrinterOutput._paper_sizes_win(printer_name)
        return {"sizes": [], "default": None}

    @staticmethod
    def _paper_sizes_cups(printer_name: str) -> dict[str, Any]:
        if not printer_name:
            return {"sizes": [], "default": None}
        try:
            r = subprocess.run(
                ["lpoptions", "-p", printer_name, "-l"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            return {"sizes": [], "default": None}
        for line in r.stdout.splitlines():
            key = line.split(":", 1)[0].split("/", 1)[0].strip()
            if key in ("PageSize", "Media Size", "MediaSize") and ":" in line:
                sizes, default = [], None
                for tok in line.split(":", 1)[1].split():
                    name = tok.lstrip("*")
                    sizes.append(name)
                    if tok.startswith("*"):
                        default = name
                return {"sizes": sizes, "default": default}
        return {"sizes": [], "default": None}

    @staticmethod
    def _paper_sizes_win(printer_name: str) -> dict[str, Any]:
        if not printer_name:
            return {"sizes": [], "default": None}
        try:
            ps = (
                f"(Get-PrintCapabilities -PrinterName '{printer_name}').PageMediaSize "
                "| Select-Object -ExpandProperty Name | ConvertTo-Json -Compress"
            )
            r = subprocess.run(["powershell.exe", "-Command", ps],
                               capture_output=True, text=True, timeout=15)
            import json
            data = json.loads(r.stdout) if r.stdout.strip() else []
            if isinstance(data, str):
                data = [data]
            return {"sizes": data, "default": None}
        except Exception:
            return {"sizes": [], "default": None}

    # ── Live printer state (paper out, cover open, offline, …) ──────────────
    # IPP printer-state-reasons keyword → (human German message). Matched as a
    # substring so vendor prefixes/suffixes (…-error/-warning/-report) still hit.
    _STATE_REASON_MAP = [
        ("media-empty", "Kein Papier / Medium leer"),
        ("media-needed", "Papier nachlegen"),
        ("media-low", "Papier fast leer"),
        ("media-jam", "Papierstau"),
        ("cover-open", "Abdeckung offen"),
        ("door-open", "Tür/Klappe offen"),
        ("input-tray-missing", "Papierfach fehlt"),
        ("marker-supply-empty", "Tinte/Farbband leer"),
        ("toner-empty", "Toner leer"),
        ("marker-supply-low", "Tinte/Farbband fast leer"),
        ("toner-low", "Toner fast leer"),
        ("marker-waste-full", "Resttank voll"),
        ("offline", "Drucker offline"),
        ("shutoff", "Drucker ausgeschaltet"),
        ("connecting-to-device", "Verbindet mit Drucker…"),
        ("timed-out", "Zeitüberschreitung"),
        ("paused", "Drucker pausiert"),
        ("spool-area-full", "Warteschlange voll"),
        ("jam", "Papierstau"),
    ]

    @staticmethod
    def _interpret_reasons(reasons: list[str]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for raw in reasons:
            r = (raw or "").strip().lower()
            if not r or r == "none":
                continue
            severity = ("error" if r.endswith("-error")
                        else "warning" if r.endswith("-warning")
                        else "info")
            msg = next((m for key, m in PrinterOutput._STATE_REASON_MAP if key in r), None)
            out.append({"reason": raw, "severity": severity, "message": msg or raw})
        return out

    @staticmethod
    def printer_status(printer_name: str) -> dict[str, Any]:
        """Live status of a printer: ready/blocked plus human-readable alerts
        (out of paper, cover open, offline, …). Reads CUPS state-reasons."""
        system = platform.system()
        if system != "Linux":
            return {"available": True, "state": "unknown", "ready": True,
                    "alerts": [], "message": "Status nur unter Linux/CUPS verfügbar."}
        try:
            import cups
        except ImportError:
            return PrinterOutput._printer_status_lpstat(printer_name)

        try:
            conn = cups.Connection()
            name = printer_name or conn.getDefault() or next(iter(conn.getPrinters()), None)
            if not name:
                return {"available": False, "state": "missing", "ready": False,
                        "alerts": [{"severity": "error", "message": "Kein Drucker gefunden", "reason": "no-printer"}],
                        "message": "Kein Drucker gefunden", "printer": None}
            attrs = conn.getPrinterAttributes(name)
            state = attrs.get("printer-state")  # 3=idle, 4=processing, 5=stopped
            raw_reasons = attrs.get("printer-state-reasons", [])
            if isinstance(raw_reasons, str):
                raw_reasons = [raw_reasons]
            alerts = PrinterOutput._interpret_reasons(list(raw_reasons))
            accepting = attrs.get("printer-is-accepting-jobs", True)
            state_name = {3: "idle", 4: "processing", 5: "stopped"}.get(state, "unknown")
            has_error = any(a["severity"] == "error" for a in alerts)
            ready = bool(accepting) and state != 5 and not has_error
            if alerts:
                message = "; ".join(a["message"] for a in alerts)
            elif state == 5:
                message = "Drucker gestoppt"
            elif not accepting:
                message = "Nimmt keine Aufträge an"
            else:
                message = "Bereit"
            return {"available": True, "printer": name, "state": state_name,
                    "ready": ready, "accepting": bool(accepting),
                    "alerts": alerts, "message": message,
                    "state_message": attrs.get("printer-state-message", "")}
        except Exception as e:
            logger.exception("CUPS status query failed")
            return {"available": False, "state": "error", "ready": False,
                    "alerts": [{"severity": "error", "message": str(e), "reason": "exception"}],
                    "message": str(e)}

    @staticmethod
    def _printer_status_lpstat(printer_name: str) -> dict[str, Any]:
        """Fallback printer status via the CUPS `lpstat` CLI (no pycups)."""
        try:
            name = printer_name
            if not name:
                d = subprocess.run(["lpstat", "-d"], capture_output=True, text=True, timeout=10)
                name = d.stdout.split(":")[-1].strip() if ":" in d.stdout else ""
            r = subprocess.run(["lpstat", "-l", "-p", name] if name else ["lpstat", "-l", "-p"],
                               capture_output=True, text=True, timeout=10)
            text = r.stdout
            low = text.lower()
            stopped = "disabled" in low or "is stopped" in low
            # Collect any reason fragments lpstat printed (indented lines)
            reasons = []
            for key, _ in PrinterOutput._STATE_REASON_MAP:
                if key in low:
                    reasons.append(key)
            alerts = PrinterOutput._interpret_reasons(reasons)
            has_error = stopped or any(a["severity"] == "error" for a in alerts)
            return {"available": True, "printer": name or "(Standard)",
                    "state": "stopped" if stopped else "idle",
                    "ready": not has_error,
                    "alerts": alerts,
                    "message": ("; ".join(a["message"] for a in alerts)
                                or ("Drucker gestoppt" if stopped else "Bereit"))}
        except Exception as e:
            return {"available": False, "state": "error", "ready": False,
                    "alerts": [{"severity": "error", "message": str(e), "reason": "exception"}],
                    "message": str(e)}

    @staticmethod
    def _list_printers_cups() -> list[dict[str, str]]:
        try:
            import cups
            conn = cups.Connection()
            printers = conn.getPrinters()
            default = conn.getDefault()
            return [
                {"name": name, "driver": info.get("printer-make-and-model", ""), "default": name == default}
                for name, info in printers.items()
            ]
        except Exception:
            # pycups not installed — fall back to the CUPS CLI
            return PrinterOutput._list_printers_lpstat()

    @staticmethod
    def _list_printers_lpstat() -> list[dict[str, str]]:
        try:
            names = subprocess.run(["lpstat", "-e"], capture_output=True, text=True, timeout=10)
            dflt = subprocess.run(["lpstat", "-d"], capture_output=True, text=True, timeout=10)
            default_name = dflt.stdout.split(":")[-1].strip() if ":" in dflt.stdout else ""
            out = []
            for n in names.stdout.split():
                n = n.strip()
                if n:
                    out.append({"name": n, "driver": "", "default": n == default_name})
            return out
        except Exception:
            return []

    def get_config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["server", "browser"], "default": "browser"},
                "printer_name": {"type": "string", "default": ""},
                "paper_size": {"type": "string", "default": "4x6"},
                "copies": {"type": "integer", "default": 1, "minimum": 1},
                "orientation": {"type": "string", "enum": ["portrait", "landscape"], "default": "portrait"},
                "fit_to_page": {"type": "boolean", "default": True},
                "margin_mm": {"type": "number", "default": 0, "minimum": 0},
            },
        }

    def get_status(self) -> dict[str, Any]:
        status = super().get_status()
        status["mode"] = self._mode
        status["printer"] = self._printer_name or "(Systemstandard)"
        status["paper_size"] = self._paper_size
        status["copies"] = self._copies
        return status
