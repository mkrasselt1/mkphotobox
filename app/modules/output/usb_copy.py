"""USB stick copy output — copies photo to a mounted USB drive."""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any

from app.modules.output.base import AbstractOutput

logger = logging.getLogger(__name__)


class USBCopyOutput(AbstractOutput):
    name = "output.usb_copy"

    def __init__(self):
        self._mount_path = "/media/usb"

    async def initialize(self, config: dict[str, Any]) -> None:
        self._mount_path = config.get("mount_path", "/media/usb")

    async def shutdown(self) -> None:
        pass

    def is_available(self) -> bool:
        return Path(self._mount_path).is_dir()

    async def send(self, photo_path: str, metadata: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._copy_sync, photo_path)

    def _copy_sync(self, photo_path: str) -> dict[str, Any]:
        src = Path(photo_path)
        dest_dir = Path(self._mount_path) / "photobox"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name

        try:
            shutil.copy2(src, dest)
            logger.info("Copied to USB: %s", dest)
            return {"status": "ok", "path": str(dest)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "mount_path": {
                    "type": "string", "default": "/media/usb",
                    "description": "USB mount point path",
                },
            },
        }
