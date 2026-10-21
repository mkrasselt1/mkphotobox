"""Abstract camera interface."""

from __future__ import annotations

import asyncio
import logging
from abc import abstractmethod
from typing import AsyncIterator

from app.modules.base import ModuleBase

logger = logging.getLogger(__name__)


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

    #: Set by modules that run background removal themselves on raw frames
    #: (OpenCV, with its own worker). Everyone else gets it in the shared
    #: preview loop below — once per frame, however many viewers watch.
    processes_background_internally = False

    _bg_remover = None

    @property
    def bg_remover(self):
        """Background removal / chroma key for this camera (lazy).

        Lived only in the OpenCV module, so with a DSLR the effects silently did
        nothing — neither live nor on the saved photo."""
        if self._bg_remover is None:
            from app.config import get_config
            from app.services.background_removal import BackgroundRemover
            self._bg_remover = BackgroundRemover()
            self._bg_remover.configure(get_config())
        return self._bg_remover

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
            if frame and not self.processes_background_internally:
                frame = await self._hub_background(frame)
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

    # ── Hintergrund in der gemeinsamen Vorschau ──────────────────────────
    _ai_mask = None
    _ai_job: asyncio.Future | None = None

    async def _hub_background(self, frame: bytes) -> bytes:
        """Chroma key per frame; AI with a mask that is refreshed in the
        background at its own pace. rembg needs far longer than one preview
        frame — waiting for it would turn the preview into a slideshow, so each
        frame is composited with the newest mask available instead."""
        try:
            bg = self.bg_remover
            if not bg.enabled:
                self._ai_mask = None
                return frame
            if bg.mode == "chromakey":
                return await asyncio.to_thread(self._bg_chromakey, bg, frame)
            if bg.mode == "ai":
                if self._ai_job is None or self._ai_job.done():
                    if (self._ai_job is not None and not self._ai_job.cancelled()
                            and self._ai_job.exception() is None):
                        self._ai_mask = self._ai_job.result()
                    self._ai_job = asyncio.ensure_future(
                        asyncio.to_thread(self._bg_ai_mask, bg, frame))
                if self._ai_mask is None:
                    return frame  # erste Maske noch in Arbeit
                return await asyncio.to_thread(self._bg_composite, bg, frame, self._ai_mask)
        except Exception:
            logger.debug("live background removal failed", exc_info=True)
        return frame

    @staticmethod
    def _decode(frame: bytes):
        import cv2
        import numpy as np
        return cv2.imdecode(np.frombuffer(frame, np.uint8), cv2.IMREAD_COLOR)

    def _encode(self, img) -> bytes:
        import cv2
        ok, jpeg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, self.preview_quality])
        return jpeg.tobytes() if ok else b""

    def _bg_chromakey(self, bg, frame: bytes) -> bytes:
        img = self._decode(frame)
        return frame if img is None else (self._encode(bg.apply(img)) or frame)

    def _bg_ai_mask(self, bg, frame: bytes):
        img = self._decode(frame)
        return None if img is None else bg.ai_mask(img)

    def _bg_composite(self, bg, frame: bytes, mask) -> bytes:
        img = self._decode(frame)
        return frame if img is None else (self._encode(bg.composite(img, mask)) or frame)

