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
        # Focus modes don't change at runtime — query once (ideally at connect,
        # before the preview stream owns the lock) and cache, so the admin UI
        # never blocks on a get_config() that contends with live preview.
        self._focus_modes_cache: dict[str, Any] | None = None
        self._focus_warm_tried = False   # one-shot warm from the preview loop
        # gphoto2 is NOT thread-safe — serialise all camera access so the
        # live-preview stream and a still capture never run concurrently
        # (that triggers "[-110] I/O in progress").
        self._lock = threading.RLock()

    async def initialize(self, config: dict[str, Any]) -> None:
        self._capture_target = config.get("capture_target", 1)
        self._focus_mode = (config.get("focus_mode") or "").strip()
        self._autofocus = bool(config.get("autofocus", False))
        if self.is_available():
            # Connect in the BACKGROUND so a wedged camera (PTP timeout + USB
            # reset recovery can take ~15s) never blocks app startup. The module
            # is registered immediately and self-heals on first capture/preview.
            try:
                self._connect_task = asyncio.create_task(self._async_connect())
            except RuntimeError:
                # no running loop (e.g. tests) — fall back to a guarded sync attempt
                try:
                    self._connect()
                except Exception as e:
                    logger.warning("gphoto2 initial connect failed (%s)", e)
                    self._camera = None

    async def _async_connect(self):
        # Hold the camera lock so the background connect can't race with a preview
        # or capture request that arrives while we're (re)connecting.
        def _locked_connect():
            with self._lock:
                if self._camera is None:
                    self._connect()
                # Warm the focus-mode cache now, while we own the lock and the
                # preview stream isn't hammering it yet.
                if self._focus_modes_cache is None:
                    self._focus_modes_cache = self._read_focus_modes_locked()
        try:
            await asyncio.to_thread(_locked_connect)
        except Exception as e:
            logger.warning("gphoto2 connect failed (%s); will retry on next use", e)
            self._camera = None

    # Known camera USB vendor IDs (for USB-reset recovery of a wedged PTP session):
    # Canon, Nikon, Sony, Fujifilm, Panasonic, Olympus
    _CAMERA_VENDORS = ("04a9", "04b0", "054c", "04cb", "04da", "07b4")

    def _free_camera_port(self):
        """Release the camera from desktop auto-mounters (gvfs) that may hold the
        PTP session. Best-effort (usually a no-op; AutoMount is off on the box)."""
        import subprocess
        for proc in ("gvfsd-gphoto2", "gvfs-gphoto2-volume-monitor"):
            try:
                subprocess.run(["pkill", "-f", proc], capture_output=True, timeout=5)
            except Exception:
                pass

    def _usb_reset(self):
        """Reset the camera's USB device (equivalent to a physical replug) to
        recover a wedged PTP session — the reliable fix when init/summary times
        out. Best-effort, Linux-only; needs usbfs write access (the same access
        gphoto2 already uses)."""
        import fcntl
        import os
        import re
        import subprocess

        USBDEVFS_RESET = (ord("U") << 8) | 20  # _IO('U', 20)
        try:
            out = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5).stdout
        except Exception:
            return
        for line in out.splitlines():
            m = re.match(r"Bus (\d+) Device (\d+): ID ([0-9a-fA-F]{4}):", line)
            if not m or m.group(3).lower() not in self._CAMERA_VENDORS:
                continue
            path = f"/dev/bus/usb/{m.group(1)}/{m.group(2)}"
            try:
                fd = os.open(path, os.O_WRONLY)
                try:
                    fcntl.ioctl(fd, USBDEVFS_RESET, 0)
                    logger.info("USB reset issued on %s (camera recovery)", path)
                finally:
                    os.close(fd)
            except Exception as e:
                logger.debug("USB reset failed on %s: %s", path, e)

    def _connect(self):
        import time as _t

        import gphoto2 as gp

        # Recovery ladder for a busy/wedged camera: plain retry → free gvfs →
        # USB reset (replug). USB reset re-enumerates the device and also wakes a
        # camera that auto-powered-off, so it fixes the common PTP-timeout case.
        last_err = None
        for attempt in range(1, 4):
            try:
                # python-gphoto2 manages a default context internally; passing an
                # explicit context positionally shifts other arguments and breaks
                # methods like file_get on current binding versions.
                self._camera = gp.Camera()
                self._camera.init()
                last_err = None
                break
            except gp.GPhoto2Error as e:
                last_err = e
                self._camera = None
                logger.warning("gphoto2 init attempt %d/3 failed: %s", attempt, e)
                if attempt == 1:
                    self._free_camera_port()
                    _t.sleep(1.5)
                else:
                    self._usb_reset()      # heavier: replug via ioctl
                    _t.sleep(4.0)          # allow re-enumeration
        if last_err is not None:
            raise last_err

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
        """Return the camera's available focus-mode choices (for the admin UI).

        Never blocks the UI: returns the cached result instantly when available,
        otherwise tries to grab the camera lock briefly — if the live preview is
        holding it, we report "busy" rather than hanging on get_config()."""
        if self._focus_modes_cache is not None:
            return self._focus_modes_cache

        # Non-blocking-ish: don't wait forever behind the preview stream.
        if not self._lock.acquire(timeout=2.0):
            return {"available": False, "reason": "Kamera beschäftigt (Vorschau aktiv) — bitte kurz erneut versuchen",
                    "choices": [], "current": "", "busy": True}
        try:
            result = self._read_focus_modes_locked()
        finally:
            self._lock.release()
        if result.get("available"):
            self._focus_modes_cache = result   # cache only a good result; retry on failure
        return result

    def _read_focus_modes_locked(self) -> dict[str, Any]:
        """Query the focus-mode widget. Caller MUST hold self._lock."""
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
                        # Opportunistically warm the focus-mode cache once, now
                        # that we hold the lock and the camera is clearly live —
                        # so the admin dropdown populates without ever contending
                        # with (or stalling) the preview stream afterwards.
                        if self._focus_modes_cache is None and not self._focus_warm_tried:
                            self._focus_warm_tried = True
                            try:
                                fm = self._read_focus_modes_locked()
                                if fm.get("available"):
                                    self._focus_modes_cache = fm
                            except Exception:
                                pass
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
