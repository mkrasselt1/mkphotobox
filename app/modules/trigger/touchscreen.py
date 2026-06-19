"""Touchscreen trigger — fires via WebSocket message from the browser."""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.modules.trigger.base import AbstractTrigger

logger = logging.getLogger(__name__)


class TouchscreenTrigger(AbstractTrigger):
    """Trigger from the booth UI touchscreen/click button.

    The actual trigger signal comes from the browser via WebSocket.
    This module just registers itself so the trigger manager knows it exists.
    The WebSocket handler calls fire() directly.
    """

    name = "trigger.touchscreen"
    _callback: Callable | None = None

    async def initialize(self, config: dict[str, Any]) -> None:
        pass

    async def shutdown(self) -> None:
        self._callback = None

    def is_available(self) -> bool:
        return True

    async def start_listening(self, callback: Callable) -> None:
        self._callback = callback

    async def stop_listening(self) -> None:
        self._callback = None

    async def fire(self) -> None:
        """Called by the WebSocket handler when the user presses the button."""
        if self._callback:
            await self._callback("trigger.fired", {"source": "touchscreen"})
