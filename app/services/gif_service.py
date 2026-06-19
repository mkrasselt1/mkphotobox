"""GIF capture service: buffers preview frames and creates animated GIFs."""

from __future__ import annotations

import asyncio
import io
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BufferedFrame:
    jpeg_bytes: bytes
    timestamp: float


class GifService:
    """Continuously buffers preview frames and creates GIFs on demand."""

    def __init__(self):
        self._buffer: deque[BufferedFrame] = deque()
        self._buffer_seconds: float = 5.0
        self._fps: int = 10
        self._running = False
        self._task: asyncio.Task | None = None
        self._enabled = False
        self._gif_width = 480
        self._gif_height = 360

    def configure(self, config: dict[str, Any]) -> None:
        gif_cfg = config.get("gif", {})
        self._enabled = gif_cfg.get("enabled", True)
        self._buffer_seconds = gif_cfg.get("buffer_seconds", 5.0)
        self._fps = gif_cfg.get("fps", 10)
        self._gif_width = gif_cfg.get("width", 480)
        self._gif_height = gif_cfg.get("height", 360)

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def start_buffering(self, camera_manager) -> None:
        """Start a background task that continuously grabs preview frames."""
        if not self._enabled:
            return
        self._running = True
        self._task = asyncio.create_task(self._buffer_loop(camera_manager))
        logger.info("GIF buffer started (%.1fs @ %dfps)", self._buffer_seconds, self._fps)

    async def _buffer_loop(self, camera_manager) -> None:
        interval = 1.0 / self._fps
        while self._running:
            try:
                cam = camera_manager.preview_camera
                if cam is not None:
                    frame = await cam.get_preview_frame()
                    if frame:
                        now = time.time()
                        self._buffer.append(BufferedFrame(jpeg_bytes=frame, timestamp=now))
                        # Trim old frames
                        cutoff = now - self._buffer_seconds
                        while self._buffer and self._buffer[0].timestamp < cutoff:
                            self._buffer.popleft()
            except Exception:
                pass  # Camera might be switching, just skip this frame
            await asyncio.sleep(interval)

    async def stop_buffering(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        self._buffer.clear()

    async def create_gif(self, output_dir: Path, filename_base: str) -> Path | None:
        """Create a GIF from the buffered frames. Returns the file path or None."""
        if not self._buffer:
            logger.warning("GIF: no frames in buffer")
            return None

        # Snapshot the current buffer
        frames = list(self._buffer)
        if len(frames) < 3:
            logger.warning("GIF: only %d frames, need at least 3", len(frames))
            return None

        return await asyncio.to_thread(
            self._build_gif, frames, output_dir, filename_base
        )

    def _build_gif(self, frames: list[BufferedFrame], output_dir: Path, filename_base: str) -> Path | None:
        try:
            from PIL import Image

            pil_frames = []
            for f in frames:
                img = Image.open(io.BytesIO(f.jpeg_bytes))
                img = img.resize((self._gif_width, self._gif_height))
                pil_frames.append(img)

            if not pil_frames:
                return None

            gif_path = output_dir / f"{filename_base}.gif"
            frame_duration = int(1000 / self._fps)  # ms per frame

            pil_frames[0].save(
                gif_path,
                save_all=True,
                append_images=pil_frames[1:],
                duration=frame_duration,
                loop=0,
                optimize=True,
            )

            # Close all frames
            for img in pil_frames:
                img.close()

            file_size = gif_path.stat().st_size
            logger.info("GIF created: %s (%d frames, %d KB)", gif_path.name, len(pil_frames), file_size // 1024)
            return gif_path

        except Exception:
            logger.exception("GIF creation failed")
            return None
