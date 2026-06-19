"""CD/DVD burning via xorriso.

Uses a single tool (xorriso) that auto-detects whether the inserted medium is a
CD or DVD and burns the selected files directly to disc — no intermediate ISO
image is written, which keeps disk usage on the Raspberry Pi low.

Burning is a long-running operation, so a burn runs as a background asyncio task
and reports progress over the event bus (-> WebSocket). Only one burn at a time.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import shutil
import subprocess
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def xorriso_available() -> bool:
    return platform.system() == "Linux" and shutil.which("xorriso") is not None


def probe_media(device: str) -> dict[str, Any]:
    """Inspect the inserted medium. Returns drive/media info.

    Detects CD vs DVD automatically via xorriso's media profile.
    """
    if not xorriso_available():
        return {
            "tool_available": False,
            "reason": "xorriso ist auf diesem System nicht installiert.",
        }

    info: dict[str, Any] = {
        "tool_available": True,
        "device": device,
        "present": False,
        "media_type": None,   # e.g. "CD-R", "DVD-R", "DVD+RW"
        "media_class": None,   # "CD" | "DVD" | None
        "status": None,        # blank | appendable | closed
        "writable": False,
        "free_mb": None,
    }
    try:
        res = subprocess.run(
            ["xorriso", "-outdev", device, "-toc"],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        info["reason"] = "Laufwerk antwortet nicht (Zeitüberschreitung)."
        return info
    except Exception as e:  # pragma: no cover - defensive
        info["reason"] = str(e)
        return info

    output = res.stdout + "\n" + res.stderr
    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("Media current:"):
            value = line.split(":", 1)[1].strip()
            if "not recognized" in value or "not present" in value:
                info["present"] = False
            else:
                info["present"] = True
                info["media_type"] = value.split()[0] if value else None
                if info["media_type"]:
                    info["media_class"] = "DVD" if "DVD" in info["media_type"].upper() else "CD"
        elif line.startswith("Media status"):
            value = line.split(":", 1)[1].strip()
            info["status"] = value
            info["writable"] = "blank" in value or "appendable" in value
        elif line.startswith("Media summary"):
            m = re.search(r"([\d.]+)([kmg])\s+free", line, re.IGNORECASE)
            if m:
                num = float(m.group(1))
                unit = m.group(2).lower()
                mb = num * {"k": 1 / 1024, "m": 1, "g": 1024}[unit]
                info["free_mb"] = round(mb, 1)

    if not info["present"]:
        info["reason"] = "Kein Medium eingelegt."
    elif not info["writable"]:
        info["reason"] = "Medium ist nicht beschreibbar (voll oder finalisiert)."
    return info


class CDBurnService:
    """Singleton-style burn job manager. One burn at a time."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._cancelled = False
        self._state: dict[str, Any] = {
            "status": "idle",       # idle | burning | completed | failed | cancelled
            "phase": "",
            "progress": 0.0,
            "message": "",
            "file_count": 0,
            "started_at": None,
            "finished_at": None,
        }

    @property
    def state(self) -> dict[str, Any]:
        return dict(self._state)

    @property
    def is_busy(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(
        self,
        files: list[tuple[str, str]],
        *,
        device: str,
        volume_label: str,
        speed: str,
        eject: bool,
        bus: Any,
    ) -> dict[str, Any]:
        """Begin burning. ``files`` is a list of (source_path, archive_name)."""
        if self.is_busy:
            return {"status": "error", "message": "Es läuft bereits ein Brennvorgang."}
        if not xorriso_available():
            return {"status": "error", "message": "xorriso ist nicht installiert."}
        if not files:
            return {"status": "error", "message": "Keine Fotos zum Brennen ausgewählt."}

        self._cancelled = False
        self._state = {
            "status": "burning",
            "phase": "Vorbereiten",
            "progress": 0.0,
            "message": f"{len(files)} Dateien werden vorbereitet…",
            "file_count": len(files),
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": None,
        }
        self._task = asyncio.create_task(
            self._run(files, device, volume_label, speed, eject, bus)
        )
        return {"status": "started", **self.state}

    async def cancel(self) -> dict[str, Any]:
        if not self.is_busy:
            return {"status": "error", "message": "Kein laufender Brennvorgang."}
        self._cancelled = True
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
            except ProcessLookupError:
                pass
        return {"status": "cancelling"}

    async def _emit(self, bus: Any) -> None:
        if bus is not None:
            await bus.emit("cd_burn.progress", self.state)

    async def _run(self, files, device, volume_label, speed, eject, bus) -> None:
        args = ["xorriso", "-outdev", device, "-volid", volume_label,
                "-joliet", "on", "-blank", "as_needed"]
        if speed:
            args += ["-speed", str(speed)]
        for src, arc in files:
            arcname = arc if arc.startswith("/") else f"/{arc}"
            args += ["-map", src, arcname]
        args += ["-commit"]
        if eject:
            args += ["-eject", "all"]

        self._state["phase"] = "Brennen"
        self._state["message"] = "Brennvorgang gestartet…"
        await self._emit(bus)

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except Exception as e:
            logger.exception("Failed to launch xorriso")
            await self._finish(bus, "failed", f"Brenner konnte nicht gestartet werden: {e}")
            return

        assert self._proc.stdout is not None
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            logger.debug("xorriso: %s", text)
            m = _PERCENT_RE.search(text)
            if m:
                pct = float(m.group(1))
                # xorriso reports several percentages; keep the highest seen
                if pct >= self._state["progress"]:
                    self._state["progress"] = pct
                    self._state["message"] = f"Brennen… {pct:.0f}%"
                    await self._emit(bus)

        rc = await self._proc.wait()

        if self._cancelled:
            await self._finish(bus, "cancelled", "Brennvorgang abgebrochen.")
        elif rc == 0:
            self._state["progress"] = 100.0
            await self._finish(bus, "completed", "Disc erfolgreich gebrannt.")
        else:
            await self._finish(bus, "failed", f"xorriso endete mit Fehlercode {rc}.")

    async def _finish(self, bus: Any, status: str, message: str) -> None:
        self._state["status"] = status
        self._state["phase"] = "Fertig"
        self._state["message"] = message
        self._state["finished_at"] = datetime.utcnow().isoformat()
        self._proc = None
        if bus is not None:
            await bus.emit("cd_burn.completed", self.state)
        logger.info("CD burn %s: %s", status, message)


_service = CDBurnService()


def get_burn_service() -> CDBurnService:
    return _service
