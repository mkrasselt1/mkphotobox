"""Lightweight in-process async event bus. No external dependencies."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)


class EventBus:
    """Async pub/sub event bus for inter-module communication."""

    def __init__(self):
        self._listeners: dict[str, list[Callable]] = defaultdict(list)

    def on(self, event: str, handler: Callable) -> None:
        """Register a handler for an event type."""
        self._listeners[event].append(handler)

    def off(self, event: str, handler: Callable) -> None:
        """Remove a handler."""
        try:
            self._listeners[event].remove(handler)
        except ValueError:
            pass

    async def emit(self, event: str, data: Any = None) -> None:
        """Fire an event to all registered handlers (non-blocking)."""
        for handler in self._listeners.get(event, []):
            asyncio.create_task(self._safe_call(handler, event, data))

    async def emit_and_wait(self, event: str, data: Any = None) -> list[Any]:
        """Fire an event and wait for all handlers to complete."""
        results = []
        for handler in self._listeners.get(event, []):
            result = await self._safe_call(handler, event, data, suppress=False)
            results.append(result)
        return results

    async def _safe_call(
        self, handler: Callable, event: str, data: Any, suppress: bool = True
    ) -> Any:
        try:
            result = handler(event, data)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception:
            logger.exception("Event handler error for '%s'", event)
            if not suppress:
                raise
            return None

    def clear(self) -> None:
        """Remove all listeners."""
        self._listeners.clear()
