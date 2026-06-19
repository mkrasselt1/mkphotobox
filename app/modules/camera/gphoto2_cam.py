"""gPhoto2 DSLR camera module (Linux only).

Requires: pip install gphoto2
Supports: Canon, Nikon, Sony, and most PTP-compatible DSLRs.
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading
from typing import Any

from app.modules.camera.base import AbstractCamera

logger = logging.getLogger(__name__)


class GPhoto2Camera(AbstractCamera):
    name = "camera.gphoto2"

    # Focus-mode config widget is named differently per brand — try in order.
    _FOCUS_WIDGETS = ("focusmode", "focusmode2", "afmode")

    def __init__(self):
        self._camera = None
        self._context = None
        self._capture_target = 1  # 1 = card, 0 = RAM
        self._focus_mode = ""     # "" = leave the camera's current setting
        self._autofocus = False   # drive autofocus right before each capture
        # gphoto2 is NOT thread-safe — serialise all camera access so the
        # live-preview stream and a still capture never run concurrently
        # (that triggers "[-110] I/O in progress").
        self._lock = threading.RLock()

    async def initialize(self, config: dict[str, Any]) -> None:
        self._capture_target = config.get("capture_target", 1)
        self._focus_mode = (config.get("focus_mode") or "").strip()
        self._autofocus = bool(config.get("autofocus", False))
        if self.is_available():
            await asyncio.to_thread(self._connect)

    def _connect(self):
        import gphoto2 as gp

        # python-gphoto2 manages a default context internally; passing an
        # explicit context positionally shifts other arguments and breaks
        # methods like file_get on current binding versions.
        self._camera = gp.Camera()
        self._camera.init()

        # Set capture target if supported
        try:
            config = self._camera.get_config()
            target = config.get_child_by_name("capturetarget")
            target.set_value(str(self._capture_target))
            self._camera.set_config(config)
        except Exception:
            logger.debug("Could not set capture target (camera may not support it)")

        # Apply configured focus mode (best-effort; brand-dependent)
        self._apply_focus_mode()

        summary = self._camera.get_summary()
        logger.info("gPhoto2 connected: %s", str(summary)[:100])

    def _apply_focus_mode(self) -> None:
        """Set the camera's focus-mode widget to the configured value.

        Brands name the widget and its choices differently (Canon "focusmode" =
        One Shot/AI Focus/AI Servo/Manual; Nikon "focusmode2"; etc.), so we match
        the requested value case-insensitively against the camera's own choices.
        """
        if not self._focus_mode or self._camera is None:
            return
        try:
            config = self._camera.get_config()
        except Exception:
            return
        for wname in self._FOCUS_WIDGETS:
            try:
                widget = config.get_child_by_name(wname)
            except Exception:
                continue
            try:
                choices = [widget.get_choice(i) for i in range(widget.count_choices())]
            except Exception:
                choices = []
            target = self._focus_mode
            if choices:
                match = (next((c for c in choices if c.lower() == target.lower()), None)
                         or next((c for c in choices if target.lower() in c.lower()), None))
                if not match:
                    logger.warning("focus_mode %r not among %s choices %s", target, wname, choices)
                    continue
                target = match
            try:
                widget.set_value(target)
                self._camera.set_config(config)
                logger.info("Focus mode set: %s = %s", wname, target)
                return
            except Exception as e:
                logger.debug("Could not set %s=%s: %s", wname, target, e)
        logger.warning("No settable focus-mode widget found for %r", self._focus_mode)

    def list_focus_modes(self) -> dict[str, Any]:
        """Return the camera's available focus-mode choices (for the admin UI)."""
        with self._lock:
            try:
                if self._camera is None:
                    self._connect()
                config = self._camera.get_config()
            except Exception as e:
                return {"available": False, "reason": str(e), "choices": [], "current": ""}
            for wname in self._FOCUS_WIDGETS:
                try:
                    widget = config.get_child_by_name(wname)
                except Exception:
                    continue
                try:
                    choices = [widget.get_choice(i) for i in range(widget.count_choices())]
                except Exception:
                    choices = []
                current = ""
                try:
                    current = widget.get_value()
                except Exception:
                    pass
                return {"available": True, "widget": wname, "choices": choices, "current": current}
        return {"available": False, "reason": "Kein Fokus-Widget gefunden", "choices": [], "current": ""}

    def _drive_autofocus(self) -> None:
        """Trigger one autofocus run (used before capture when enabled)."""
        if self._camera is None:
            return
        try:
            config = self._camera.get_config()
            af = config.get_child_by_name("autofocusdrive")
            af.set_value(1)
            self._camera.set_config(config)
        except Exception as e:
            logger.debug("Autofocus drive not supported / failed: %s", e)

    async def shutdown(self) -> None:
        if self._camera is not None:
            try:
                await asyncio.to_thread(self._camera.exit)
            except Exception:
                pass
            self._camera = None
            self._context = None

    def is_available(self) -> bool:
        try:
            import gphoto2  # noqa: F401
            return True
        except ImportError:
            return False

    async def capture(self) -> bytes:
        """Capture a full-resolution photo from the DSLR."""
        return await asyncio.to_thread(self._capture_sync)

    def _capture_sync(self) -> bytes:
        import gphoto2 as gp

        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._camera is None:
                        self._connect()
                    if self._autofocus:
                        self._drive_autofocus()
                    file_path = self._camera.capture(gp.GP_CAPTURE_IMAGE)
                    logger.info("Captured: %s/%s", file_path.folder, file_path.name)
                    camera_file = self._camera.file_get(
                        file_path.folder, file_path.name, gp.GP_FILE_TYPE_NORMAL
                    )
                    return bytes(camera_file.get_data_and_size())
                except gp.GPhoto2Error as e:
                    logger.warning("Capture attempt %d failed (%s); re-init camera", attempt, e)
                    self._reset()
                    if attempt == 2:
                        raise
            return b""

    def _reset(self):
        """Drop and re-acquire the camera handle (recovers from I/O errors)."""
        try:
            if self._camera is not None:
                self._camera.exit()
        except Exception:
            pass
        self._camera = None

    async def get_preview_frame(self) -> bytes:
        """Get a live preview frame from the DSLR viewfinder."""
        return await asyncio.to_thread(self._preview_sync)

    def _preview_sync(self) -> bytes:
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._camera is None:
                        self._connect()
                    camera_file = self._camera.capture_preview()
                    data = bytes(camera_file.get_data_and_size())
                    if data:
                        return data
                    logger.debug("Empty preview frame; re-init camera (attempt %d)", attempt)
                except Exception as e:
                    logger.debug("Preview error: %s; re-init camera (attempt %d)", e, attempt)
                self._reset()  # drop the bad handle so the next try reconnects
            return b""

    def get_config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "capture_target": {
                    "type": "integer",
                    "default": 1,
                    "description": "0 = RAM (faster), 1 = Memory Card",
                    "enum": [0, 1],
                },
                "focus_mode": {
                    "type": "string",
                    "default": "",
                    "description": "Fokus-Modus (z. B. 'One Shot', 'AI Servo', 'Manual'). "
                                   "Leer = Kamera-Einstellung beibehalten.",
                },
                "autofocus": {
                    "type": "boolean",
                    "default": False,
                    "description": "Vor jeder Aufnahme autofokussieren.",
                },
            },
        }

    def get_status(self) -> dict[str, Any]:
        status = super().get_status()
        if self._camera is not None:
            try:
                summary = str(self._camera.get_summary())
                status["model"] = summary.split("\n")[0] if summary else "Connected"
            except Exception:
                status["model"] = "Connected (status unavailable)"
        return status
