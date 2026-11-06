"""Abstract camera interface."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from abc import abstractmethod
from typing import Any, AsyncIterator, Callable

from app.modules.base import ModuleBase

logger = logging.getLogger(__name__)


class AbstractCamera(ModuleBase):
    """Base for every camera module.

    Modules implement the synchronous hooks ``_capture_sync`` /
    ``_preview_sync`` (plus optionally open/pause/resume/release). They run
    only in the camera's one thread (:mod:`app.modules.camera.worker`); the
    configured geometry (rotation, flip, mirrored preview) is applied on top —
    see :mod:`app.services.image_transform`. Callers always use the public
    ``capture`` / ``get_preview_frame`` / ``stream_preview`` / ``call``.
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

    #: Woher die Vorschau kommt — fürs Admin-UI (get_status()["preview_source"]):
    #: "stream" = echter Videostrom (Webcam, HDMI-Grabber an der DSLR),
    #: "liveview" = Live-View-Einzelbilder in enger Schleife (DSLR über USB/PTP
    #: kann technisch nichts anderes; ``gphoto2 --capture-movie`` macht intern
    #: dasselbe), "browser" = die Vorschau läuft im Browser.
    preview_source = "liveview"

    # ── Hooks für den Kamera-Thread ──────────────────────────────────────
    # Laufen AUSSCHLIESSLICH im Kamera-Thread (siehe worker.py). Wer die Kamera
    # sonst noch anfassen will, gibt einen Auftrag über ``call()`` ab.

    @abstractmethod
    def _capture_sync(self) -> bytes:
        """Full-resolution photo, JPEG bytes, untransformed."""
        ...

    @abstractmethod
    def _preview_sync(self) -> bytes:
        """Next preview frame (JPEG, low resolution, untransformed); b"" if none."""
        ...

    def _open_sync(self) -> None:
        """Connect when the thread starts (failure is retried on first use)."""

    def _stream_start_sync(self) -> None:
        """Live-View resumes (before the first frame after a pause/photo)."""

    def _stream_stop_sync(self, for_capture: bool = False) -> None:
        """Live-View pauses: before a photo (``for_capture``) and when nobody
        watches."""

    def _release_sync(self) -> None:
        """Release the device; last thing the thread does."""

    # ── Öffentliche API ──────────────────────────────────────────────────

    async def capture_raw(self) -> bytes:
        """Full-resolution photo — as a job for the camera thread, which stops
        the Live-View for it and restarts it afterwards."""
        return await self.call(self._capture_sync, pauses_stream=True)

    async def preview_frame_raw(self) -> bytes:
        """Newest untransformed preview frame from the shared stream."""
        return await self._latest("_hub_raw")

    async def capture(self) -> bytes:
        """Full-resolution photo with the configured geometry applied."""
        return await self._transformed(await self.capture_raw(), preview=False)

    async def get_preview_frame(self) -> bytes:
        """Newest preview frame with the configured geometry applied (no
        background effects — the colour picker needs the real colours).

        Comes from the shared stream, never from the camera directly: a
        snapshot used to fire its own capture_preview past the stream."""
        return await self._latest("_hub_plain")

    async def _transform_preview(self, data: bytes) -> bytes:
        """Geometry for preview frames (mirrored preview included)."""
        return await self._transformed(data, preview=True)

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

    async def call(self, fn: Callable[..., Any], *args, pauses_stream: bool = False,
                   timeout: float | None = None) -> Any:
        """Run ``fn(*args)`` in the camera thread and return its result.

        The only way to reach the device from outside — config queries
        included. Jobs go ahead of the next preview frame."""
        fut = self._get_worker().submit(fn, *args, pauses_stream=pauses_stream)
        wrapped = asyncio.wrap_future(fut)
        if timeout is None:
            return await wrapped
        return await asyncio.wait_for(wrapped, timeout)

    def get_status(self) -> dict[str, Any]:
        status = super().get_status()
        status["preview_source"] = self.preview_source
        status["stream_state"] = self._stream_state
        return status

    # ── Kamera-Thread und Verteiler ──────────────────────────────────────

    #: Upper bound for the preview stream. A DSLR is usually slower.
    preview_max_fps = 15

    _worker = None
    _closed = False
    _hub_cond: asyncio.Condition | None = None
    #: "off" (Thread nie gestartet) | "idle" | "live" | "capturing"
    _stream_state = "off"

    def _get_worker(self):
        if self._closed:
            raise RuntimeError(f"{self.name}: Kamera wurde beendet")
        self._ensure_hub()
        if self._worker is None:
            from app.modules.camera.worker import CameraWorker
            self._worker = CameraWorker(
                self, on_frame=self._frame_from_thread, on_state=self._state_from_thread,
                max_fps=self.preview_max_fps)
            self._stream_state = "idle"
        return self._worker

    def _ensure_hub(self) -> None:
        if self._hub_cond is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._hub_cond = asyncio.Condition()
        self._hub_raw = self._hub_plain = self._hub_frame = b""
        self._hub_seq, self._hub_time = 0, 0.0
        self._hub_viewers = 0
        self._hub_pending: bytes | None = None
        self._hub_ready = asyncio.Event()
        self._hub_task = self._loop.create_task(self._hub_process())

    # Diese beiden laufen im Kamera-Thread: nur übergeben, nichts rechnen.
    def _frame_from_thread(self, frame: bytes) -> None:
        try:
            self._loop.call_soon_threadsafe(self._hub_in, frame)
        except RuntimeError:
            pass  # Loop schon zu (Dienst fährt herunter)

    def _state_from_thread(self, state: str) -> None:
        try:
            self._loop.call_soon_threadsafe(setattr, self, "_stream_state", state)
        except RuntimeError:
            pass

    def _hub_in(self, frame: bytes) -> None:
        # Nur das neueste Rohbild merken: ist die Aufbereitung langsamer als
        # die Kamera, fallen Zwischenbilder weg statt sich zu stauen.
        self._hub_pending = frame
        self._hub_ready.set()

    async def _hub_process(self) -> None:
        """Geometry and background effects — once per frame, however many
        viewers watch."""
        while not self._closed:
            await self._hub_ready.wait()
            self._hub_ready.clear()
            raw, self._hub_pending = self._hub_pending, None
            if not raw:
                continue
            try:
                plain = await self._transform_preview(raw)
            except Exception:
                logger.debug("preview transform failed", exc_info=True)
                plain = raw
            final = plain
            if plain and not self.processes_background_internally:
                final = await self._hub_background(plain)
            if not plain:
                continue
            async with self._hub_cond:
                self._hub_raw, self._hub_plain, self._hub_frame = raw, plain, final
                self._hub_seq += 1
                self._hub_time = time.monotonic()
                self._hub_cond.notify_all()

    async def stream_preview(self, *, passive: bool = False) -> AsyncIterator[bytes]:
        """Async generator yielding JPEG preview frames — for any number of viewers.

        One camera thread per camera, not one reader per viewer: every viewer
        (booth screen, admin page on a phone, a stale <img> left over from the
        last screen) gets each new frame; a slow one simply gets the newest
        frame next time instead of a backlog. The first viewer starts the
        Live-View, a few seconds after the last one leaves it pauses.

        ``passive`` subscribers take frames while the stream runs anyway but
        don't keep it running — for the GIF buffer, which otherwise would hold
        the DSLR in Live-View day and night.
        """
        async for frame in self._subscribe("_hub_frame", passive=passive):
            yield frame

    async def _subscribe(self, attr: str, *, passive: bool = False) -> AsyncIterator[bytes]:
        if self._closed:
            return
        self._ensure_hub()
        cond = self._hub_cond
        # Ein frisches Bild sofort zeigen; ein altes (Live-View war pausiert)
        # nicht — sonst bekäme der Schnappschuss ein Bild von vor Minuten.
        fresh = self._hub_seq and time.monotonic() - self._hub_time < 1.0
        seen = self._hub_seq - 1 if fresh else self._hub_seq
        if not passive:
            self._hub_viewers += 1
            self._get_worker().set_streaming(True)
        try:
            while not self._closed:
                async with cond:
                    try:
                        # Timeout nur, damit ein beendeter Kamera-Thread den
                        # Zuschauer nicht ewig hängen lässt. Während eines Fotos
                        # kommen keine Bilder: die Verbindung bleibt offen, der
                        # Browser zeigt das letzte Bild weiter.
                        await asyncio.wait_for(cond.wait_for(
                            lambda: self._hub_seq != seen or self._closed), timeout=2.0)
                    except asyncio.TimeoutError:
                        continue
                    if self._closed:
                        return
                    seen, frame = self._hub_seq, getattr(self, attr)
                yield frame
        finally:
            if not passive:
                self._hub_viewers -= 1
                if self._hub_viewers <= 0 and self._worker is not None:
                    self._worker.set_streaming(False)

    async def _latest(self, attr: str, *, max_age: float = 1.0, timeout: float = 10.0) -> bytes:
        """Newest frame of the shared stream; starts the Live-View briefly if
        nothing current is there (the idle grace then pauses it again)."""
        if self._closed:
            return b""
        self._ensure_hub()
        if self._hub_seq and time.monotonic() - self._hub_time <= max_age:
            frame = getattr(self, attr)
            if frame:
                return frame

        async def first() -> bytes:
            async with contextlib.aclosing(self._subscribe(attr)) as frames:
                async for frame in frames:
                    if frame:
                        return frame
            return b""
        try:
            return await asyncio.wait_for(first(), timeout)
        except asyncio.TimeoutError:
            return b""

    async def _stop_worker(self, timeout: float = 2.5) -> None:
        """End the camera thread (it releases the device itself) — bounded,
        so a camera stuck in a USB call can't hold up the service restart
        (uvicorn gives us 3 s). The thread is a daemon: if it doesn't make it,
        the process exits without it."""
        self._closed = True
        worker = self._worker
        if self._hub_cond is not None:
            self._hub_ready.set()  # Aufbereitung aufwecken, damit sie endet
            async with self._hub_cond:
                self._hub_cond.notify_all()
        if worker is None:
            return
        worker.stop()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        # Pollen statt join() im Executor: der Default-Executor wartet beim
        # Beenden auf alle seine Threads — genau das ließ den Neustart hängen.
        while worker.alive_thread and loop.time() < deadline:
            await asyncio.sleep(0.05)
        if worker.alive_thread:
            logger.warning("%s: Kamera-Thread reagiert nicht, Prozess endet ohne ihn", self.name)
        self._stream_state = "off"

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

