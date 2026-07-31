"""Abstract camera interface."""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from typing import AsyncIterator

from app.modules.base import ModuleBase


class AbstractCamera(ModuleBase):
    """Base for every camera module.

    Modules implement ``capture_raw`` / ``preview_frame_raw`` and get the
    configured geometry (rotation, flip, mirrored preview) applied for free —
    see :mod:`app.services.image_transform`. Callers always use the public
    ``capture`` / ``get_preview_frame``.
    """

    category = "camera"

    #: Set by modules that rotate/flip in their own, cheaper representation —
    #: OpenCV works on numpy frames instead of paying a JPEG round-trip.
    transforms_internally = False

    #: JPEG quality used when a transform forces a re-encode.
    capture_quality = 92
    preview_quality = 75

    @abstractmethod
    async def capture_raw(self) -> bytes:
        """Capture a full-resolution photo. Returns JPEG bytes."""
        ...

    @abstractmethod
    async def preview_frame_raw(self) -> bytes:
        """Return a single JPEG preview frame (low resolution)."""
        ...

    async def capture(self) -> bytes:
        """Full-resolution photo with the configured geometry applied."""
        return await self._transformed(await self.capture_raw(), preview=False)

    async def get_preview_frame(self) -> bytes:
        """Preview frame with the configured geometry applied."""
        return await self._transformed(await self.preview_frame_raw(), preview=True)

    async def _transformed(self, data: bytes, *, preview: bool) -> bytes:
        if self.transforms_internally or not data:
            return data
        from app.services.image_transform import Transform, apply_to_jpeg

        tf = Transform.current()
        if tf.is_noop(preview):
            return data
        quality = self.preview_quality if preview else self.capture_quality
        return await asyncio.to_thread(
            apply_to_jpeg, data, tf, preview=preview, quality=quality
        )

    async def stream_preview(self) -> AsyncIterator[bytes]:
        """Async generator yielding JPEG preview frames."""
        while True:
            yield await self.get_preview_frame()
            await asyncio.sleep(1 / 15)  # 15 fps cap for RPi3
