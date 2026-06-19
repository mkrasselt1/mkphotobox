"""Background removal using rembg (AI-based) + simple chroma key fallback.

Three modes:
- **ai**: Uses rembg/u2net — works on any background, no setup needed.
  Slower (~1-2s per frame on RPi3) so only applied to capture, not live preview.
- **chromakey**: Fast HSV-based color keying — works in real-time for preview.
- **none**: Disabled.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# rembg session is heavy — create once, reuse
_rembg_session = None


def _get_rembg_session():
    global _rembg_session
    if _rembg_session is None:
        from rembg import new_session
        _rembg_session = new_session("u2net")
        logger.info("rembg AI model loaded (u2net)")
    return _rembg_session


class BackgroundRemover:
    """Removes background from camera frames."""

    def __init__(self):
        self._enabled = False
        self._mode = "none"  # none | ai | chromakey
        # Chroma key settings
        self._key_hue = 60
        self._key_tolerance = 30
        self._key_saturation_min = 50
        self._feather = 3
        # Replacement
        self._replacement_color = (0, 0, 0)
        self._replacement_image: np.ndarray | None = None
        # AI mode: cache last mask for preview performance
        self._last_ai_mask: np.ndarray | None = None

    def configure(self, config: dict[str, Any]) -> None:
        bg_cfg = config.get("background_removal", {})
        self._enabled = bg_cfg.get("enabled", False)
        self._mode = bg_cfg.get("mode", "none")
        self._key_hue = bg_cfg.get("chromakey_hue", 60)
        self._key_tolerance = bg_cfg.get("chromakey_tolerance", 30)
        self._key_saturation_min = bg_cfg.get("chromakey_saturation_min", 50)
        self._feather = bg_cfg.get("feather", 3)

        replacement_hex = bg_cfg.get("replacement_color", "#000000")
        self._replacement_color = self._hex_to_bgr(replacement_hex)

        repl_path = bg_cfg.get("replacement_image", "")
        if repl_path and Path(repl_path).exists():
            self.load_replacement_image(repl_path)

    @property
    def enabled(self) -> bool:
        return self._enabled and self._mode != "none"

    @property
    def mode(self) -> str:
        return self._mode

    def get_status(self) -> dict[str, Any]:
        rembg_available = False
        try:
            import rembg  # noqa: F401
            rembg_available = True
        except ImportError:
            pass

        return {
            "enabled": self._enabled,
            "mode": self._mode,
            "rembg_available": rembg_available,
            "has_replacement_image": self._replacement_image is not None,
            "chromakey_hue": self._key_hue,
            "chromakey_tolerance": self._key_tolerance,
        }

    # ── Chroma key ────────────────────────────────────────────────────

    def set_chromakey_from_pixel(self, bgr_color: tuple[int, int, int]) -> None:
        import cv2
        pixel = np.uint8([[list(bgr_color)]])
        hsv = cv2.cvtColor(pixel, cv2.COLOR_BGR2HSV)
        self._key_hue = int(hsv[0, 0, 0])
        logger.info("Chroma key hue=%d (from BGR %s)", self._key_hue, bgr_color)

    # ── Apply ─────────────────────────────────────────────────────────

    def apply(self, frame: np.ndarray) -> np.ndarray:
        """Apply background removal. For live preview, use chromakey.
        For final capture, use AI mode."""
        if not self.enabled:
            return frame
        if self._mode == "chromakey":
            return self._apply_chromakey(frame)
        if self._mode == "ai":
            return self._apply_ai(frame)
        return frame

    def apply_to_capture(self, frame: np.ndarray) -> np.ndarray:
        """Apply background removal optimized for final capture (higher quality).
        Always uses AI if available, regardless of preview mode."""
        if not self.enabled:
            return frame
        # For capture, always prefer AI if available
        try:
            return self._apply_ai(frame)
        except Exception:
            logger.debug("AI bg removal failed for capture, falling back to current mode")
            return self.apply(frame)

    def _apply_ai(self, frame: np.ndarray) -> np.ndarray:
        """Remove background using rembg AI model."""
        import cv2
        from rembg import remove

        session = _get_rembg_session()

        # rembg expects PIL Image or bytes
        _, jpeg = cv2.imencode(".jpg", frame)
        result_bytes = remove(
            jpeg.tobytes(),
            session=session,
            bgcolor=None,  # transparent
        )

        # Decode result (RGBA PNG)
        result_arr = np.frombuffer(result_bytes, np.uint8)
        result = cv2.imdecode(result_arr, cv2.IMREAD_UNCHANGED)

        if result is None or result.shape[2] < 4:
            return frame

        # Extract alpha channel as mask
        alpha = result[:, :, 3]

        # Composite over replacement background
        return self._composite(frame, alpha)

    def _apply_chromakey(self, frame: np.ndarray) -> np.ndarray:
        """Fast HSV-based chroma key — suitable for real-time preview."""
        import cv2

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        hue_low = max(0, self._key_hue - self._key_tolerance)
        hue_high = min(180, self._key_hue + self._key_tolerance)

        lower = np.array([hue_low, self._key_saturation_min, 40])
        upper = np.array([hue_high, 255, 255])
        key_mask = cv2.inRange(hsv, lower, upper)

        fg_mask = cv2.bitwise_not(key_mask)

        if self._feather > 0:
            k = self._feather * 2 + 1
            kernel = np.ones((k, k), np.uint8)
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
            fg_mask = cv2.GaussianBlur(fg_mask, (k * 2 + 1, k * 2 + 1), 0)

        return self._composite(frame, fg_mask)

    def _composite(self, frame: np.ndarray, fg_mask: np.ndarray) -> np.ndarray:
        """Blend foreground over replacement background using mask."""
        import cv2

        alpha = fg_mask.astype(np.float32) / 255.0
        if alpha.ndim == 2:
            alpha = alpha[:, :, np.newaxis]

        if self._replacement_image is not None:
            bg = self._replacement_image
            if bg.shape[:2] != frame.shape[:2]:
                bg = cv2.resize(bg, (frame.shape[1], frame.shape[0]))
        else:
            bg = np.full_like(frame, self._replacement_color)

        result = (frame.astype(np.float32) * alpha + bg.astype(np.float32) * (1.0 - alpha))
        return result.astype(np.uint8)

    # ── Helpers ───────────────────────────────────────────────────────

    def load_replacement_image(self, path: str) -> None:
        import cv2
        img = cv2.imread(path)
        if img is not None:
            self._replacement_image = img
            logger.info("Replacement background loaded: %s", path)

    @staticmethod
    def _hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
        hex_color = hex_color.lstrip("#")
        if len(hex_color) != 6:
            return (0, 0, 0)
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        return (b, g, r)
