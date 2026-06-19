"""WebSocket connection manager with role-based broadcasting."""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WSManager:
    """Manages WebSocket connections and broadcasts messages."""

    def __init__(self):
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, ws: WebSocket, role: str = "user") -> None:
        await ws.accept()
        self._connections[role].add(ws)
        logger.debug("WS connected: role=%s, total=%d", role, self.count)

    def disconnect(self, ws: WebSocket, role: str = "user") -> None:
        self._connections[role].discard(ws)
        logger.debug("WS disconnected: role=%s, total=%d", role, self.count)

    @property
    def count(self) -> int:
        return sum(len(s) for s in self._connections.values())

    async def broadcast(
        self, msg_type: str, data: dict | None = None, roles: list[str] | None = None
    ) -> None:
        """Send a JSON message to all connected clients, optionally filtered by role."""
        message = json.dumps({"type": msg_type, "data": data or {}, "ts": time.time()})
        target_roles = roles or list(self._connections.keys())
        for role in target_roles:
            dead: set[WebSocket] = set()
            for ws in self._connections.get(role, set()):
                try:
                    await ws.send_text(message)
                except Exception:
                    dead.add(ws)
            self._connections[role] -= dead

    async def send_to(self, ws: WebSocket, msg_type: str, data: dict | None = None) -> None:
        """Send a message to a specific client."""
        message = json.dumps({"type": msg_type, "data": data or {}, "ts": time.time()})
        try:
            await ws.send_text(message)
        except Exception:
            logger.debug("Failed to send to WS client")
