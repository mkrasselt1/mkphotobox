"""GPIO button trigger for Raspberry Pi."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from app.modules.trigger.base import AbstractTrigger

logger = logging.getLogger(__name__)


class GPIOTrigger(AbstractTrigger):
    name = "trigger.gpio"

    def __init__(self):
        self._pin = 17
        self._pull_up = True
        self._debounce_ms = 300
        self._callback: Callable | None = None
        self._running = False
        self._task = None

    async def initialize(self, config: dict[str, Any]) -> None:
        self._pin = config.get("pin", 17)
        self._pull_up = config.get("pull_up", True)
        self._debounce_ms = config.get("debounce_ms", 300)

    async def shutdown(self) -> None:
        await self.stop_listening()
        if self.is_available():
            try:
                import RPi.GPIO as GPIO
                GPIO.cleanup(self._pin)
            except Exception:
                pass

    def is_available(self) -> bool:
        try:
            import RPi.GPIO  # noqa: F401
            return True
        except ImportError:
            return False

    async def start_listening(self, callback: Callable) -> None:
        self._callback = callback
        self._running = True

        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        pull = GPIO.PUD_UP if self._pull_up else GPIO.PUD_DOWN
        GPIO.setup(self._pin, GPIO.IN, pull_up_down=pull)

        # Use a background task that polls (more reliable than edge detection
        # with asyncio, and works across different RPi models)
        self._task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self):
        import RPi.GPIO as GPIO

        last_state = GPIO.input(self._pin)
        trigger_value = 0 if self._pull_up else 1  # Button press pulls to opposite

        while self._running:
            await asyncio.sleep(self._debounce_ms / 1000)
            current = GPIO.input(self._pin)
            if current == trigger_value and last_state != trigger_value:
                if self._callback:
                    await self._callback("trigger.fired", {"source": "gpio", "pin": self._pin})
            last_state = current

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
                "pin": {"type": "integer", "default": 17, "description": "BCM GPIO pin number"},
                "pull_up": {"type": "boolean", "default": True, "description": "Enable internal pull-up resistor"},
                "debounce_ms": {"type": "integer", "default": 300, "description": "Debounce time in milliseconds"},
            },
        }
