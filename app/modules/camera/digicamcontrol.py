"""digiCamControl camera module (Windows only).

Uses the digiCamControl HTTP API to control DSLRs on Windows.
digiCamControl must be running separately: http://digicamcontrol.com/
Default API endpoint: http://localhost:5513
"""

from __future__ import annotations

import asyncio
import logging
import platform
from typing import Any
from urllib.request import urlopen, Request
from urllib.error import URLError

from app.modules.camera.base import AbstractCamera
from app.modules.base import missing_python_package

logger = logging.getLogger(__name__)


class DigiCamCamera(AbstractCamera):
    name = "camera.digicamcontrol"

    def __init__(self):
        self._host = "localhost"
        self._port = 5513
        self._base_url = ""

    async def initialize(self, config: dict[str, Any]) -> None:
        self._host = config.get("host", "localhost")
        self._port = config.get("port", 5513)
        self._base_url = f"http://{self._host}:{self._port}"

    async def shutdown(self) -> None:
        pass

    @classmethod
    def system_requirement(cls) -> str | None:
        if platform.system() != "Windows":
            return "digiCamControl gibt es nur für Windows"
        return None

    def is_available(self) -> bool:
        if platform.system() != "Windows":
            return False
        try:
            resp = urlopen(f"{self._base_url}/", timeout=2)
            return resp.status == 200
        except (URLError, OSError):
            return False

    async def capture(self) -> bytes:
        """Trigger capture via digiCamControl and retrieve the photo."""
        return await asyncio.to_thread(self._capture_sync)

    def _capture_sync(self) -> bytes:
        # Trigger capture
        resp = urlopen(f"{self._base_url}/?CMD=Capture", timeout=15)
        if resp.status != 200:
            raise RuntimeError(f"digiCamControl capture failed: HTTP {resp.status}")

        # Get the last captured photo path
        resp = urlopen(f"{self._base_url}/?CMD=GetLastImage", timeout=5)
        last_image_path = resp.read().decode("utf-8").strip()

        if not last_image_path or last_image_path.startswith("error"):
            raise RuntimeError(f"digiCamControl: no image: {last_image_path}")

        # Read the file from disk (digiCamControl saves it locally)
        from pathlib import Path
        img_path = Path(last_image_path)
        if not img_path.exists():
            raise RuntimeError(f"Image file not found: {last_image_path}")

        data = img_path.read_bytes()

        # If it's not a JPEG, convert it
        if not last_image_path.lower().endswith(('.jpg', '.jpeg')):
            data = self._convert_to_jpeg(data)

        return data

    def _convert_to_jpeg(self, data: bytes) -> bytes:
        """Convert RAW/TIFF/etc. to JPEG using Pillow."""
        import io
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        img.close()
        return buf.getvalue()

    async def get_preview_frame(self) -> bytes:
        """Get a live preview frame from digiCamControl."""
        return await asyncio.to_thread(self._preview_sync)

    def _preview_sync(self) -> bytes:
        try:
            resp = urlopen(f"{self._base_url}/?CMD=LiveViewImage", timeout=3)
            if resp.status == 200:
                return resp.read()
        except (URLError, OSError) as e:
            logger.debug("digiCamControl preview error: %s", e)
        return b""

    def get_config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "default": "localhost",
                    "description": "digiCamControl server host",
                },
                "port": {
                    "type": "integer",
                    "default": 5513,
                    "description": "digiCamControl server port",
                },
            },
        }

    def get_status(self) -> dict[str, Any]:
        status = super().get_status()
        status["url"] = self._base_url
        if self.is_available():
            try:
                resp = urlopen(f"{self._base_url}/?CMD=GetDeviceName", timeout=2)
                status["model"] = resp.read().decode("utf-8").strip()
            except Exception:
                status["model"] = "Connected"
        return status
