"""Copy photos to a removable medium (USB drive, SD card, USB stick).

A faster, no-blank-needed alternative to CD/DVD burning. Detects mounted
removable media so the target can be picked before copying, then copies the
selected photos with live progress over the event bus (-> WebSocket).
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_REMOVABLE_ROOTS = ("/media", "/run/media", "/mnt")


def list_drives() -> list[dict[str, Any]]:
    """List mounted, writable removable media. Empty list if none/unsupported."""
    system = platform.system()
    if system == "Linux":
        return _list_drives_linux()
    if system == "Windows":
        return _list_drives_windows()
    return []


def _disk_free(mountpoint: str) -> tuple[Optional[int], Optional[int]]:
    try:
        usage = shutil.disk_usage(mountpoint)
        return usage.total, usage.free
    except Exception:
        return None, None


def _list_drives_linux() -> list[dict[str, Any]]:
    try:
        res = subprocess.run(
            ["lsblk", "-J", "-b", "-o",
             "NAME,TYPE,RM,HOTPLUG,MOUNTPOINT,LABEL,FSTYPE,VENDOR,MODEL"],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(res.stdout)
    except Exception:
        logger.exception("lsblk failed")
        return []

    drives: list[dict[str, Any]] = []

    def walk(node: dict, parent_removable: bool) -> None:
        removable = parent_removable or bool(node.get("rm")) or bool(node.get("hotplug"))
        mountpoint = node.get("mountpoint")
        if mountpoint:
            is_removable_mount = mountpoint.startswith(_REMOVABLE_ROOTS)
            if (removable or is_removable_mount) and mountpoint not in ("/", "/boot"):
                total, free = _disk_free(mountpoint)
                label = node.get("label") or node.get("model") or node.get("name")
                drives.append({
                    "id": mountpoint,
                    "mountpoint": mountpoint,
                    "label": (label or "").strip() or mountpoint,
                    "fstype": node.get("fstype") or "",
                    "size_bytes": total,
                    "free_bytes": free,
                    "removable": True,
                    "model": (node.get("model") or "").strip(),
                })
        for child in node.get("children", []) or []:
            walk(child, removable)

    for node in data.get("blockdevices", []) or []:
        walk(node, False)
    return drives


def _list_drives_windows() -> list[dict[str, Any]]:
    try:
        res = subprocess.run(
            ["powershell.exe", "-Command",
             "Get-Volume | Where-Object { $_.DriveType -eq 'Removable' -and $_.DriveLetter } "
             "| Select-Object DriveLetter,FileSystemLabel,FileSystem,Size,SizeRemaining "
             "| ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(res.stdout) if res.stdout.strip() else []
    except Exception:
        return []
    if isinstance(data, dict):
        data = [data]
    drives = []
    for v in data:
        letter = v.get("DriveLetter")
        if not letter or not v.get("Size"):
            continue  # empty card-reader slot / no medium inserted
        mountpoint = f"{letter}:\\"
        drives.append({
            "id": mountpoint,
            "mountpoint": mountpoint,
            "label": v.get("FileSystemLabel") or mountpoint,
            "fstype": v.get("FileSystem") or "",
            "size_bytes": v.get("Size"),
            "free_bytes": v.get("SizeRemaining"),
            "removable": True,
            "model": "",
        })
    return drives


class USBExportService:
    """Single copy job at a time, mirroring the CD burn service."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._cancelled = False
        self._state: dict[str, Any] = {
            "status": "idle",   # idle | copying | completed | failed | cancelled
            "progress": 0.0,
            "message": "",
            "copied": 0,
            "file_count": 0,
            "target": None,
            "started_at": None,
            "finished_at": None,
        }

    @property
    def state(self) -> dict[str, Any]:
        return dict(self._state)

    @property
    def is_busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def validate_space(self, files: list[tuple[str, str]], free_bytes: Optional[int]) -> Optional[str]:
        """Return an error message if the medium is too small, else None."""
        if free_bytes is None:
            return None
        total = 0
        for src, _ in files:
            try:
                total += Path(src).stat().st_size
            except OSError:
                pass
        if total > free_bytes:
            need = total / 1_048_576
            have = free_bytes / 1_048_576
            return f"Nicht genug Speicher: {need:.0f} MB benötigt, {have:.0f} MB frei."
        return None

    async def start(self, files, *, mountpoint: str, subfolder: str, bus: Any,
                    include_viewer: bool = True) -> dict[str, Any]:
        if self.is_busy:
            return {"status": "error", "message": "Es läuft bereits ein Kopiervorgang."}
        if not files:
            return {"status": "error", "message": "Keine Fotos zum Kopieren ausgewählt."}
        if not Path(mountpoint).is_dir():
            return {"status": "error", "message": f"Zielmedium '{mountpoint}' nicht gefunden."}

        self._cancelled = False
        self._state = {
            "status": "copying",
            "progress": 0.0,
            "message": f"Kopiere {len(files)} Dateien…",
            "copied": 0,
            "file_count": len(files),
            "target": mountpoint,
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": None,
        }
        self._task = asyncio.create_task(
            self._run(files, mountpoint, subfolder, bus, include_viewer))
        return {"status": "started", **self.state}

    async def cancel(self) -> dict[str, Any]:
        if not self.is_busy:
            return {"status": "error", "message": "Kein laufender Kopiervorgang."}
        self._cancelled = True
        return {"status": "cancelling"}

    async def _emit(self, bus: Any) -> None:
        if bus is not None:
            await bus.emit("usb_export.progress", self.state)

    async def _run(self, files, mountpoint, subfolder, bus, include_viewer=True) -> None:
        dest_dir = Path(mountpoint) / subfolder if subfolder else Path(mountpoint)
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            await self._finish(bus, "failed", f"Zielordner nicht beschreibbar: {e}")
            return

        total = len(files)
        copied_images: list[str] = []
        for idx, (src, name) in enumerate(files, start=1):
            if self._cancelled:
                await self._finish(bus, "cancelled", "Kopiervorgang abgebrochen.")
                return
            try:
                fname = Path(name).name
                await asyncio.to_thread(shutil.copy2, src, dest_dir / fname)
                if fname.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                    copied_images.append(fname)
            except Exception as e:
                await self._finish(bus, "failed", f"Fehler bei '{name}': {e}")
                return
            self._state["copied"] = idx
            self._state["progress"] = round(idx / total * 100, 1)
            self._state["message"] = f"Kopiere… {idx}/{total} ({name})"
            await self._emit(bus)

        # Drop a standalone offline gallery viewer next to the photos so the
        # stick can be browsed by just opening index.html (no app needed).
        if include_viewer and copied_images:
            try:
                await asyncio.to_thread(_write_viewer, dest_dir, copied_images)
            except Exception:
                logger.exception("Could not write USB viewer")

        # Flush filesystem buffers so the medium can be safely removed
        try:
            await asyncio.to_thread(_sync_fs)
        except Exception:
            pass
        await self._finish(bus, "completed", f"{total} Dateien nach {dest_dir} kopiert.")

    async def _finish(self, bus: Any, status: str, message: str) -> None:
        self._state["status"] = status
        self._state["message"] = message
        self._state["finished_at"] = datetime.utcnow().isoformat()
        if status == "completed":
            self._state["progress"] = 100.0
        if bus is not None:
            await bus.emit("usb_export.completed", self.state)
        logger.info("USB export %s: %s", status, message)


def _sync_fs() -> None:
    if platform.system() == "Linux":
        subprocess.run(["sync"], timeout=30)


def _write_viewer(dest_dir: Path, image_names: list[str]) -> None:
    """Write a standalone offline gallery (index.html + photos.js) into *dest_dir*.

    Opening index.html (file://) shows a responsive grid + lightbox with no app,
    server or internet needed. The photo list is embedded as a JS file (not JSON)
    so it loads under file:// where fetch() is blocked."""
    from app.services.viewer_assets import VIEWER_HTML, viewer_photos_js

    (dest_dir / "photos.js").write_text(
        viewer_photos_js(image_names), encoding="utf-8")
    (dest_dir / "index.html").write_text(VIEWER_HTML, encoding="utf-8")


_service = USBExportService()


def get_export_service() -> USBExportService:
    return _service
