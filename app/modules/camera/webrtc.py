"""WebRTC browser camera module.

This is a "virtual" camera — the actual capture happens in the browser via
getUserMedia(). The server receives the captured frame as a JPEG upload.
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.camera.base import AbstractCamera

logger = logging.getLogger(__name__)


class WebRTCCamera(AbstractCamera):
    """Browser-based camera via WebRTC.

    Preview is handled entirely client-side. Capture is a JPEG POST from
    the browser. This module acts as a thin shim so the camera manager
    can treat all cameras uniformly.
    """

    name = "camera.webrtc"
    _last_frame: bytes | None = None

    async def initialize(self, config: dict[str, Any]) -> None:
        pass

    async def shutdown(self) -> None:
        self._last_frame = None

    def is_available(self) -> bool:
        return True  # always available — the browser does the work

    async def capture_raw(self) -> bytes:
        if self._last_frame is None:
            raise RuntimeError(
                "No frame received from browser. "
                "Ensure the client posts the captured frame to the server."
            )
        return self._last_frame

    async def preview_frame_raw(self) -> bytes:
        if self._last_frame is None:
            # Return a 1x1 transparent JPEG placeholder
            return b""
        return self._last_frame

    async def get_preview_frame(self) -> bytes:
        """Rotation/flip yes, mirroring no.

        For this camera the live image the guests see is the browser's own
        <video> element, which the booth mirrors in CSS. Mirroring here as well
        would double it — and these frames also feed the GIF buffer, which must
        match the saved photo."""
        return await self._transformed(await self.preview_frame_raw(), preview=False)

    async def receive_frame(self, jpeg_bytes: bytes) -> None:
        """Called by the API when the browser sends a captured frame."""
        self._last_frame = jpeg_bytes
