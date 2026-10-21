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

    #: Upper bound for the shared preview loop. A DSLR is usually slower.
    preview_max_fps = 15

    async def stream_preview(self) -> AsyncIterator[bytes]:
        """Async generator yielding JPEG preview frames — for any number of viewers.

        One producer per camera, not one per viewer: the camera serialises
        preview requests behind a lock, so every extra viewer (booth screen,
        admin page on a phone, a stale <img> left over from the last screen)
        used to divide the frame rate instead of sharing it. Now the first
        viewer starts a single loop, every viewer gets each new frame, and the
        loop stops when the last one leaves.
        """
        if getattr(self, "_hub_cond", None) is None:
            self._hub_cond = asyncio.Condition()
            self._hub_frame, self._hub_seq = b"", 0
            self._hub_viewers, self._hub_task = 0, None
        cond = self._hub_cond
        self._hub_viewers += 1
        seen = -1
        try:
            while True:
                if self._hub_task is None or self._hub_task.done():
                    self._hub_task = asyncio.create_task(self._hub_produce())
                async with cond:
                    try:
                        # Timeout only to re-check the producer: it may have been
                        # winding down just as this viewer arrived.
                        await asyncio.wait_for(
                            cond.wait_for(lambda: self._hub_seq != seen), timeout=2.0)
                    except asyncio.TimeoutError:
                        continue
                    seen, frame = self._hub_seq, self._hub_frame
                yield frame
        finally:
            self._hub_viewers -= 1

    async def _hub_produce(self) -> None:
        loop = asyncio.get_running_loop()
        interval = 1 / self.preview_max_fps
        while self._hub_viewers > 0:
            started = loop.time()
            try:
                frame = await self.get_preview_frame()
            except Exception:
                frame = b""
            if frame:
                async with self._hub_cond:
                    self._hub_frame = frame
                    self._hub_seq += 1
                    self._hub_cond.notify_all()
            else:
                await asyncio.sleep(0.2)  # camera busy (capturing) or gone
            rest = interval - (loop.time() - started)
            if rest > 0:
                await asyncio.sleep(rest)
