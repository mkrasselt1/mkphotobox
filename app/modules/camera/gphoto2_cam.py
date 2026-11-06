"""gPhoto2 DSLR camera module (Linux only).

Requires: pip install gphoto2
Supports: Canon, Nikon, Sony, and most PTP-compatible DSLRs.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import time
from typing import Any

from app.modules.camera.base import AbstractCamera
from app.modules.base import missing_python_package

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
        # Focus modes don't change at runtime — query once at connect and
        # cache, so the admin UI doesn't need a camera round-trip every time.
        self._focus_modes_cache: dict[str, Any] | None = None
        # Modell aus get_summary(), beim Verbinden gemerkt: get_status() lief
        # früher aus dem Request-Thread direkt auf die Kamera — an der
        # Live-View vorbei, und gphoto2 ist nicht threadsicher.
        self._model = ""
        # Vor dem Foto Live-View aus: Canon fokussiert dann mit dem schnellen
        # Phasen-AF über den Spiegel statt mit dem langsamen Kontrast-AF der
        # Live-View. Abschaltbar, falls eine Kamera das schlecht verträgt.
        self._liveview_off_for_capture = True
        # Kein Lock mehr: die Kamera fasst nur noch ihr eigener Thread an
        # (worker.py) — das schließt "[-110] I/O in progress" durch
        # gleichzeitige Vorschau und Aufnahme grundsätzlich aus.

    async def initialize(self, config: dict[str, Any]) -> None:
        self._capture_target = config.get("capture_target", 1)
        self._focus_mode = (config.get("focus_mode") or "").strip()
        self._autofocus = bool(config.get("autofocus", False))
        self._liveview_off_for_capture = bool(config.get("liveview_off_for_capture", True))
        if self.is_available():
            # Start the camera thread now: it connects in the BACKGROUND, so a
            # wedged camera (PTP timeout + USB reset recovery can take ~15s)
            # never blocks app startup. Preview/capture self-heal on first use.
            self._get_worker()

    def _open_sync(self) -> None:
        """Kamera-Thread: erste Verbindung + Fokus-Modi einmal abfragen."""
        try:
            if self._camera is None:
                self._connect()
        except Exception as e:
            logger.warning("gphoto2 connect failed (%s); will retry on next use", e)
            self._camera = None
            return
        if self._focus_modes_cache is None:
            result = self._read_focus_modes_sync()
            if result.get("available"):
                self._focus_modes_cache = result

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

        summary = str(self._camera.get_summary())
        # Die erste Zeile ist "Manufacturer: Canon Inc." — das Modell steht in
        # "Model: Canon EOS 700D".
        model = next((ln.split(":", 1)[1].strip() for ln in summary.splitlines()
                      if ln.strip().lower().startswith("model:")), "")
        self._model = model or (summary.split("\n")[0] if summary else "Connected")
        logger.info("gPhoto2 connected: %s", summary[:100])

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

    async def list_focus_modes(self) -> dict[str, Any]:
        """Return the camera's available focus-mode choices (for the admin UI).

        Cached after the first good answer; otherwise a job for the camera
        thread, which slots it in before the next preview frame. Only a
        running photo or (re)connect can delay it — then "busy" rather than
        hanging the admin page."""
        if self._focus_modes_cache is not None:
            return self._focus_modes_cache
        try:
            result = await self.call(self._read_focus_modes_sync, timeout=5.0)
        except asyncio.TimeoutError:
            return {"available": False, "reason": "Kamera beschäftigt — bitte kurz erneut versuchen",
                    "choices": [], "current": "", "busy": True}
        except Exception as e:
            return {"available": False, "reason": str(e), "choices": [], "current": ""}
        if result.get("available"):
            self._focus_modes_cache = result   # cache only a good result; retry on failure
        return result

    def _read_focus_modes_sync(self) -> dict[str, Any]:
        """Query the focus-mode widget. Camera thread only."""
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
        """Release the camera cleanly (gphoto2 exit) so the next process can open
        it — otherwise a restart leaves a wedged PTP session (black stream).
        The camera thread does the exit() itself, after its current call, so
        it never runs mid-preview; time-bounded so a stuck camera can't hang
        the whole app shutdown."""
        await self._stop_worker()

    def _release_sync(self) -> None:
        if self._camera is not None:
            try:
                self._camera.exit()
            except Exception:
                pass
            self._camera = None
            self._context = None

    @classmethod
    def system_requirement(cls) -> str | None:
        if platform.system() == "Windows":
            return "gPhoto2 läuft nicht unter Windows — digiCamControl verwenden"
        return missing_python_package(
            "gphoto2", "sudo apt install libgphoto2-dev && pip install gphoto2")

    def is_available(self) -> bool:
        try:
            import gphoto2  # noqa: F401
            return True
        except ImportError:
            return False

    def _capture_sync(self) -> bytes:
        """Kamera-Thread: Foto. Live-View ist schon aus (Worker hat
        ``_stream_stop_sync`` gerufen); der nächste capture_preview startet sie
        von selbst wieder."""
        import gphoto2 as gp

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
                data = bytes(camera_file.get_data_and_size())
                self._drain_events()
                return data
            except gp.GPhoto2Error as e:
                logger.warning("Capture attempt %d failed (%s); re-init camera", attempt, e)
                self._reset()
                if attempt == 2:
                    raise
        return b""

    def _drain_events(self, budget: float = 0.5) -> None:
        """Canon meldet nach dem Foto noch Ereignisse (Datei hinzugefügt,
        Einstellungen geändert). Bleiben sie liegen, scheitert der erste
        capture_preview danach gern mit "I/O in progress" — also abholen, bis
        die Kamera ruhig ist, höchstens ``budget`` Sekunden."""
        import gphoto2 as gp

        end = time.monotonic() + budget
        try:
            while time.monotonic() < end:
                ev, _data = self._camera.wait_for_event(50)
                if ev == gp.GP_EVENT_TIMEOUT:
                    return
        except Exception:
            logger.debug("wait_for_event nach Aufnahme fehlgeschlagen", exc_info=True)

    def _reset(self):
        """Drop and re-acquire the camera handle (recovers from I/O errors)."""
        try:
            if self._camera is not None:
                self._camera.exit()
        except Exception:
            pass
        self._camera = None

    def _preview_sync(self) -> bytes:
        """Kamera-Thread: ein Live-View-Bild. In enger Schleife gerufen ist das
        der Videostrom einer DSLR über USB — PTP kennt nichts anderes; der
        erste Aufruf schaltet die Live-View ein (Spiegel hoch)."""
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

    def _stream_stop_sync(self, for_capture: bool = False) -> None:
        """Kamera-Thread: Live-View aus (Canon: Widget "viewfinder" = 0, der
        Spiegel klappt runter). Vor dem Foto nur, wenn so eingestellt — beim
        Pausieren ohne Zuschauer immer, das schont Sensor und Akku."""
        if self._camera is None:
            return
        if for_capture and not self._liveview_off_for_capture:
            return
        self._set_viewfinder(0)

    def _set_viewfinder(self, value: int) -> None:
        # get_single_config holt nur das eine Widget — der ganze Konfigbaum
        # einer EOS braucht eine knappe Sekunde, und die stünde vor jedem Foto.
        try:
            try:
                widget = self._camera.get_single_config("viewfinder")
                widget.set_value(value)
                self._camera.set_single_config("viewfinder", widget)
                return
            except AttributeError:
                pass  # alte python-gphoto2/libgphoto2 ohne single_config
            config = self._camera.get_config()
            widget = config.get_child_by_name("viewfinder")
            widget.set_value(value)
            self._camera.set_config(config)
        except Exception as e:
            logger.debug("viewfinder=%s nicht setzbar: %s", value, e)

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
                "liveview_off_for_capture": {
                    "type": "boolean",
                    "default": True,
                    "description": "Live-View vor dem Foto ausschalten (Spiegel-AF, "
                                   "schneller). Aus = direkt aus der Live-View auslösen.",
                },
            },
        }

    def get_status(self) -> dict[str, Any]:
        status = super().get_status()
        if self._camera is not None:
            status["model"] = self._model or "Connected"
        return status
