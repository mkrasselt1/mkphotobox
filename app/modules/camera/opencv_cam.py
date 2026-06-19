"""OpenCV USB webcam camera module with rotation/flip/background removal.

AI background removal runs in a separate worker thread so it doesn't
block the live preview. The preview shows the latest processed frame
(~1 fps with AI) while the camera keeps reading at full speed.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from app.modules.camera.base import AbstractCamera

logger = logging.getLogger(__name__)


class OpenCVCamera(AbstractCamera):
    name = "camera.opencv"

    def __init__(self):
        self._cap = None
        self._device_index = 0
        self._preview_size = (640, 480)
        self._bg_remover = None
        self._lock = threading.Lock()
        # AI bg removal runs in a background thread
        self._ai_thread: threading.Thread | None = None
        self._ai_running = False
        self._ai_result: bytes | None = None  # latest AI-processed JPEG
        self._ai_input_frame = None            # latest raw frame for AI

    async def initialize(self, config: dict[str, Any]) -> None:
        self._device_index = config.get("device_index", 0)
        self._bg_remover = None

    async def shutdown(self) -> None:
        self._ai_running = False
        if self._ai_thread and self._ai_thread.is_alive():
            self._ai_thread.join(timeout=3)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def is_available(self) -> bool:
        try:
            import cv2  # noqa: F401
            return True
        except ImportError:
            return False

    def _ensure_opened(self):
        if self._cap is None:
            import cv2
            import platform

            if platform.system() == "Windows":
                self._cap = cv2.VideoCapture(self._device_index, cv2.CAP_DSHOW)
            else:
                self._cap = cv2.VideoCapture(self._device_index)

            if not self._cap.isOpened():
                raise RuntimeError(f"Cannot open camera device {self._device_index}")

            for _ in range(5):
                self._cap.read()

    @property
    def bg_remover(self):
        if self._bg_remover is None:
            from app.services.background_removal import BackgroundRemover
            from app.config import get_config
            self._bg_remover = BackgroundRemover()
            self._bg_remover.configure(get_config())
        return self._bg_remover

    def get_raw_frame(self):
        """Read a raw numpy frame from the camera. Thread-safe."""
        with self._lock:
            self._ensure_opened()
            ret, frame = self._cap.read()
        if not ret:
            raise RuntimeError("Failed to read frame")
        return frame

    def _apply_geometry(self, frame):
        """Apply rotation and flip (fast)."""
        import cv2
        from app.config import get_config

        cfg = get_config()
        transform = cfg.get("cameras", {}).get("transform", {})
        rotation = transform.get("rotation", 0)
        flip_h = transform.get("flip_horizontal", False)
        flip_v = transform.get("flip_vertical", False)

        if rotation == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif rotation == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif rotation == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        if flip_h and flip_v:
            frame = cv2.flip(frame, -1)
        elif flip_h:
            frame = cv2.flip(frame, 1)
        elif flip_v:
            frame = cv2.flip(frame, 0)

        return frame

    # ── AI background worker ──────────────────────────────────────────

    def _ensure_ai_worker(self):
        """Start the AI worker thread if bg removal is active and it's not running."""
        bg = self.bg_remover
        if not bg.enabled:
            return
        if self._ai_thread and self._ai_thread.is_alive():
            return
        self._ai_running = True
        self._ai_thread = threading.Thread(target=self._ai_worker_loop, daemon=True)
        self._ai_thread.start()
        logger.info("AI background removal worker started")

    def _stop_ai_worker(self):
        self._ai_running = False
        self._ai_result = None

    def _ai_worker_loop(self):
        """Continuously processes frames through rembg in a background thread."""
        import cv2
        while self._ai_running:
            frame = self._ai_input_frame
            if frame is None:
                time.sleep(0.05)
                continue

            try:
                bg = self._bg_remover
                if bg and bg.enabled and bg.mode == "ai":
                    processed = bg.apply_to_capture(frame)
                    processed = cv2.resize(processed, self._preview_size)
                    _, jpeg = cv2.imencode(".jpg", processed, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    self._ai_result = jpeg.tobytes()
                elif bg and bg.enabled and bg.mode == "chromakey":
                    processed = bg.apply(frame)
                    processed = cv2.resize(processed, self._preview_size)
                    _, jpeg = cv2.imencode(".jpg", processed, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    self._ai_result = jpeg.tobytes()
                else:
                    self._ai_result = None
            except Exception:
                logger.debug("AI worker error", exc_info=True)
                self._ai_result = None

            time.sleep(0.02)  # small pause to not spin-lock

    # ── Public API ────────────────────────────────────────────────────

    async def capture(self) -> bytes:
        return await asyncio.to_thread(self._capture_sync)

    def _capture_sync(self) -> bytes:
        """Capture a frame with geometry only. BG removal applied by the endpoint."""
        import cv2
        frame = self.get_raw_frame()
        frame = self._apply_geometry(frame)
        _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return jpeg.tobytes()

    async def get_preview_frame(self) -> bytes:
        return await asyncio.to_thread(self._preview_sync)

    def _preview_sync(self) -> bytes:
        import cv2
        frame = self.get_raw_frame()
        frame = self._apply_geometry(frame)

        # Feed the AI worker
        self._ai_input_frame = frame.copy()

        bg = self.bg_remover
        if bg.enabled:
            # Start AI worker if needed
            self._ensure_ai_worker()
            # If AI has a processed result, use it
            if self._ai_result is not None:
                return self._ai_result
            # Otherwise fall through to unprocessed frame

        frame = cv2.resize(frame, self._preview_size)
        _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return jpeg.tobytes()
