"""Web upload output — uploads photo to a URL and provides a QR download link."""

from __future__ import annotations

import asyncio
import logging
import secrets
from pathlib import Path
from typing import Any

from app.modules.output.base import AbstractOutput

logger = logging.getLogger(__name__)


class WebUploadOutput(AbstractOutput):
    name = "output.web_upload"

    def __init__(self):
        self._base_url = ""

    async def initialize(self, config: dict[str, Any]) -> None:
        self._base_url = config.get("base_url", "")

    async def shutdown(self) -> None:
        pass

    def is_available(self) -> bool:
        # Always available — even without base_url it serves local download links
        return True

    def requires_network(self) -> bool:
        return bool(self._base_url)

    async def send(self, photo_path: str, metadata: dict[str, Any]) -> dict[str, Any]:
        photo_id = metadata.get("photo_id")

        if self._base_url:
            # Upload to external server
            result = await asyncio.to_thread(self._upload_sync, photo_path)
            return result

        # Local mode: just return the local download URL
        download_url = f"/api/v1/photos/{photo_id}/file" if photo_id else ""
        return {
            "status": "ok",
            "download_url": download_url,
        }

    def _upload_sync(self, photo_path: str) -> dict[str, Any]:
        """Upload photo to external server."""
        from urllib.request import Request, urlopen

        try:
            photo = Path(photo_path)
            if not photo.exists():
                return {"status": "error", "message": "Photo file not found"}

            data = photo.read_bytes()
            boundary = secrets.token_hex(16)
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{photo.name}"\r\n'
                f"Content-Type: image/jpeg\r\n\r\n"
            ).encode() + data + f"\r\n--{boundary}--\r\n".encode()

            req = Request(
                self._base_url,
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST",
            )
            resp = urlopen(req, timeout=30)
            if resp.status == 200:
                return {"status": "ok", "download_url": resp.read().decode("utf-8").strip()}
            return {"status": "error", "message": f"Upload failed: HTTP {resp.status}"}

        except Exception as e:
            logger.exception("Web upload failed")
            return {"status": "error", "message": str(e)}

    def get_config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "base_url": {
                    "type": "string",
                    "description": "External upload URL (leave empty for local download links)",
                },
            },
        }
