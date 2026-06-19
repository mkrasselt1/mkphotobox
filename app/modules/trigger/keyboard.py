"""Keyboard trigger — fires via WebSocket keypress from the browser."""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.modules.trigger.base import AbstractTrigger

logger = logging.getLogger(__name__)


class KeyboardTrigger(AbstractTrigger):
    name = "trigger.keyboard"
    _callback: Callable | None = None
    _key: str = "space"

    async def initialize(self, config: dict[str, Any]) -> None:
        self._key = config.get("key", "space")

    async def shutdown(self) -> None:
        self._callback = None

    def is_available(self) -> bool:
        return True

    async def start_listening(self, callback: Callable) -> None:
        self._callback = callback

    async def stop_listening(self) -> None:
        self._callback = None

    async def fire(self, key: str) -> None:
        """Called by the WebSocket handler on keypress."""
        if self._callback and key == self._key:
            await self._callback("trigger.fired", {"source": "keyboard", "key": key})

    def get_config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "key": {"type": "string", "default": "space", "description": "Trigger key name"},
            },
        }
