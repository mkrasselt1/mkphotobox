"""Bluetooth output — sends photo via Bluetooth OBEX push (Linux only)."""

from __future__ import annotations

import asyncio
import logging
import platform
from typing import Any

from app.modules.output.base import AbstractOutput

logger = logging.getLogger(__name__)


class BluetoothOutput(AbstractOutput):
    name = "output.bluetooth"

    async def initialize(self, config: dict[str, Any]) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def is_available(self) -> bool:
        if platform.system() != "Linux":
            return False
        # Check if bluetooth-sendto or obexftp is available
        import shutil
        return shutil.which("bluetooth-sendto") is not None or shutil.which("obexftp") is not None

    async def send(self, photo_path: str, metadata: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._send_sync, photo_path)

    def _send_sync(self, photo_path: str) -> dict[str, Any]:
        import subprocess
        import shutil

        if shutil.which("bluetooth-sendto"):
            result = subprocess.run(
                ["bluetooth-sendto", photo_path],
                timeout=60, capture_output=True,
            )
            if result.returncode == 0:
                return {"status": "ok"}

        return {"status": "error", "message": "Bluetooth send not available"}
