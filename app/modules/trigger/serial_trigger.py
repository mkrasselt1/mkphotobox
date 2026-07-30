"""Serial port trigger — fires on receiving a configurable signal."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from app.modules.trigger.base import AbstractTrigger
from app.modules.base import missing_python_package

logger = logging.getLogger(__name__)


class SerialTrigger(AbstractTrigger):
    name = "trigger.serial"

    def __init__(self):
        self._port = "/dev/ttyUSB0"
        self._baud = 9600
        self._trigger_byte = b"\n"  # Default: newline triggers
        self._callback: Callable | None = None
        self._running = False
        self._task = None

    async def initialize(self, config: dict[str, Any]) -> None:
        self._port = config.get("port", "/dev/ttyUSB0")
        self._baud = config.get("baud", 9600)
        trigger_str = config.get("trigger_string", "\n")
        self._trigger_byte = trigger_str.encode("utf-8")

    async def shutdown(self) -> None:
        await self.stop_listening()

    @classmethod
    def system_requirement(cls) -> str | None:
        return missing_python_package("serial", "pip install pyserial")

    def is_available(self) -> bool:
        try:
            import serial  # noqa: F401
            return True
        except ImportError:
            return False

    async def start_listening(self, callback: Callable) -> None:
        self._callback = callback
        self._running = True
        self._task = asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        import serial

        try:
            ser = serial.Serial(self._port, self._baud, timeout=0.5)
            logger.info("Serial trigger listening on %s @ %d baud", self._port, self._baud)
            buffer = b""
            while self._running:
                data = await asyncio.to_thread(ser.read, 64)
                if data:
                    buffer += data
                    if self._trigger_byte in buffer:
                        buffer = b""
                        if self._callback:
                            await self._callback("trigger.fired", {
                                "source": "serial",
                                "port": self._port,
                            })
                await asyncio.sleep(0.01)
            ser.close()
        except Exception:
            logger.exception("Serial trigger error on %s", self._port)

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
                "port": {"type": "string", "default": "/dev/ttyUSB0", "description": "Serial port"},
                "baud": {"type": "integer", "default": 9600, "description": "Baud rate"},
                "trigger_string": {"type": "string", "default": "\\n", "description": "String that triggers capture"},
            },
        }
