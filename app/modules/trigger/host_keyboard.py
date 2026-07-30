"""Host keyboard trigger — listens for USB HID keyboard input on the server.

Uses evdev on Linux (works headless, perfect for RPi) and pynput on Windows.
Unlike the browser keyboard trigger, this captures keypresses from physical
keyboards connected to the host machine, not the browser client.
"""

from __future__ import annotations

import asyncio
import logging
import platform
from typing import Any, Callable

from app.modules.trigger.base import AbstractTrigger
from app.modules.base import missing_python_package

logger = logging.getLogger(__name__)


class HostKeyboardTrigger(AbstractTrigger):
    name = "trigger.host_keyboard"

    def __init__(self):
        self._callback: Callable | None = None
        self._running = False
        self._task = None
        self._key_code: str = ""  # empty = any key triggers
        self._device_name: str = ""  # empty = all input devices

    async def initialize(self, config: dict[str, Any]) -> None:
        self._key_code = config.get("key_code", "")
        self._device_name = config.get("device_name", "")

    async def shutdown(self) -> None:
        await self.stop_listening()

    @classmethod
    def system_requirement(cls) -> str | None:
        if platform.system() == "Linux":
            return missing_python_package("evdev", "pip install evdev")
        if platform.system() == "Windows":
            return missing_python_package("pynput", "pip install pynput")
        return "Nur unter Linux und Windows verfügbar"

    def is_available(self) -> bool:
        system = platform.system()
        if system == "Linux":
            try:
                import evdev  # noqa: F401
                return True
            except ImportError:
                return False
        elif system == "Windows":
            try:
                import pynput  # noqa: F401
                return True
            except ImportError:
                return False
        return False

    async def start_listening(self, callback: Callable) -> None:
        self._callback = callback
        self._running = True
        system = platform.system()
        if system == "Linux":
            self._task = asyncio.create_task(self._listen_evdev())
        elif system == "Windows":
            self._task = asyncio.create_task(self._listen_pynput())

    async def stop_listening(self) -> None:
        self._running = False
        self._callback = None
        if self._task:
            self._task.cancel()
            self._task = None

    # ── Linux: evdev ─────────────────────────────────────────────────

    async def _listen_evdev(self):
        import evdev

        while self._running:
            try:
                devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
                # Filter for keyboard-capable devices (EV_KEY capability)
                kb_devices = []
                for d in devices:
                    caps = d.capabilities(verbose=False)
                    if evdev.ecodes.EV_KEY in caps:
                        # Optional: filter by device name
                        if self._device_name and self._device_name.lower() not in d.name.lower():
                            continue
                        kb_devices.append(d)

                if not kb_devices:
                    logger.debug("No keyboard devices found, retrying in 3s...")
                    await asyncio.sleep(3)
                    continue

                logger.info("Host keyboard listening on %d device(s): %s",
                            len(kb_devices), ", ".join(d.name for d in kb_devices))

                # Listen on all keyboard devices concurrently
                tasks = [
                    asyncio.create_task(self._read_device(d))
                    for d in kb_devices
                ]
                # Wait until one fails or we stop
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
                for t in pending:
                    t.cancel()

            except Exception:
                logger.debug("Host keyboard error, retrying in 3s...", exc_info=True)
                await asyncio.sleep(3)

    async def _read_device(self, device):
        import evdev

        async for event in device.async_read_loop():
            if not self._running:
                break
            # KEY_DOWN events only (value=1)
            if event.type == evdev.ecodes.EV_KEY and event.value == 1:
                key_name = evdev.ecodes.KEY.get(event.code, f"KEY_{event.code}")
                if isinstance(key_name, list):
                    key_name = key_name[0]

                # Check if we should only trigger on specific key
                if self._key_code and str(key_name) != self._key_code:
                    continue

                logger.info("Host keyboard trigger: %s from %s", key_name, device.name)
                if self._callback:
                    await self._callback("trigger.fired", {
                        "source": "host_keyboard",
                        "key": str(key_name),
                        "device": device.name,
                    })

    # ── Windows: pynput ──────────────────────────────────────────────

    async def _listen_pynput(self):
        from pynput import keyboard
        loop = asyncio.get_event_loop()

        def on_press(key):
            if not self._running:
                return False  # Stop listener
            try:
                key_name = key.char if hasattr(key, 'char') and key.char else str(key).replace("Key.", "")
            except AttributeError:
                key_name = str(key).replace("Key.", "")

            if self._key_code and key_name != self._key_code:
                return

            logger.info("Host keyboard trigger: %s", key_name)
            if self._callback:
                loop.call_soon_threadsafe(
                    asyncio.ensure_future,
                    self._callback("trigger.fired", {
                        "source": "host_keyboard",
                        "key": key_name,
                        "device": "pynput",
                    })
                )

        try:
            listener = keyboard.Listener(on_press=on_press)
            listener.start()
            while self._running:
                await asyncio.sleep(0.5)
            listener.stop()
        except Exception:
            logger.exception("pynput keyboard listener error")

    def get_config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "key_code": {
                    "type": "string", "default": "",
                    "description": "Key code to trigger on (empty = any key). Use learn mode to set.",
                },
                "device_name": {
                    "type": "string", "default": "",
                    "description": "Filter by device name (partial match, empty = all keyboards)",
                },
            },
        }
