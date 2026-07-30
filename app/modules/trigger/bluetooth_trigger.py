"""Bluetooth trigger — supports BLE button / HID remote shutter.

Works by listening for HID input events from a paired Bluetooth device.
Most cheap Bluetooth camera remotes present as a HID keyboard sending
Volume Up or Enter key events.
"""

from __future__ import annotations

import asyncio
import logging
import platform
from typing import Any, Callable

from app.modules.trigger.base import AbstractTrigger
from app.modules.base import missing_python_package

logger = logging.getLogger(__name__)


class BluetoothTrigger(AbstractTrigger):
    name = "trigger.bluetooth"

    def __init__(self):
        self._callback: Callable | None = None
        self._running = False
        self._task = None
        self._device_name = ""

    async def initialize(self, config: dict[str, Any]) -> None:
        self._device_name = config.get("device_name", "")

    async def shutdown(self) -> None:
        await self.stop_listening()

    @classmethod
    def system_requirement(cls) -> str | None:
        if platform.system() != "Linux":
            return "Bluetooth-Remote nur unter Linux"
        return missing_python_package("evdev", "pip install evdev")

    def is_available(self) -> bool:
        # Only available on Linux with evdev
        if platform.system() != "Linux":
            return False
        try:
            import evdev  # noqa: F401
            return True
        except ImportError:
            return False

    async def start_listening(self, callback: Callable) -> None:
        self._callback = callback
        self._running = True
        self._task = asyncio.create_task(self._listen_loop())

    async def _listen_loop(self):
        import evdev

        while self._running:
            try:
                devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
                # Find Bluetooth HID devices
                bt_devices = [
                    d for d in devices
                    if "bluetooth" in d.phys.lower() or "bt" in d.name.lower()
                    or (self._device_name and self._device_name.lower() in d.name.lower())
                ]

                if not bt_devices:
                    logger.debug("No Bluetooth HID device found, retrying in 5s...")
                    await asyncio.sleep(5)
                    continue

                device = bt_devices[0]
                logger.info("Bluetooth trigger connected to: %s (%s)", device.name, device.path)

                async for event in device.async_read_loop():
                    if not self._running:
                        break
                    # KEY_DOWN events (value=1) for common remote keys
                    if event.type == evdev.ecodes.EV_KEY and event.value == 1:
                        key = evdev.ecodes.KEY.get(event.code, f"KEY_{event.code}")
                        # Common BT remote keys: Enter, Volume Up, Space
                        if event.code in (
                            evdev.ecodes.KEY_ENTER,
                            evdev.ecodes.KEY_VOLUMEUP,
                            evdev.ecodes.KEY_SPACE,
                            evdev.ecodes.KEY_CAMERA,
                        ):
                            logger.info("Bluetooth trigger: key=%s", key)
                            if self._callback:
                                await self._callback("trigger.fired", {
                                    "source": "bluetooth",
                                    "key": str(key),
                                    "device": device.name,
                                })

            except Exception:
                logger.debug("Bluetooth trigger error, retrying in 5s...", exc_info=True)
                await asyncio.sleep(5)

    async def stop_listening(self) -> None:
        self._running = False
        self._callback = None
        if self._task:
            self._task.cancel()
            self._task = None

    def get_config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "device_name": {
                    "type": "string", "default": "",
                    "description": "Bluetooth device name filter (optional, matches partial)",
                },
            },
        }
