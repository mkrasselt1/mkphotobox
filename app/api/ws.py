"""WebSocket endpoint for real-time communication."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError

from app.auth import decode_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/api/v1/ws")
async def websocket_endpoint(ws: WebSocket, token: str = Query(default="")):
    app = ws.app
    ws_manager = app.state.ws_manager

    # Determine role from token (user if no/invalid token)
    role = "user"
    if token:
        try:
            payload = decode_token(token)
            role = payload.get("role", "user")
        except (JWTError, Exception):
            pass

    await ws_manager.connect(ws, role)
    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")
            msg_data = msg.get("data", {})

            await _handle_client_message(app, ws, role, msg_type, msg_data)

    except WebSocketDisconnect:
        ws_manager.disconnect(ws, role)
    except Exception:
        logger.exception("WebSocket error")
        ws_manager.disconnect(ws, role)


async def _handle_client_message(app, ws, role: str, msg_type: str, data: dict):
    """Process incoming WebSocket messages from clients."""
    bus = app.state.bus
    ws_manager = app.state.ws_manager

    if msg_type == "trigger.fire":
        # Touchscreen/keyboard trigger from the browser
        source = data.get("source", "touchscreen")
        await bus.emit("trigger.fired", {"source": source})

    elif msg_type == "preview.start":
        # Client requests live preview — only relevant for server-side cameras
        await ws_manager.send_to(ws, "preview.ack", {"status": "started"})

    elif msg_type == "preview.stop":
        await ws_manager.send_to(ws, "preview.ack", {"status": "stopped"})

    elif msg_type == "ping":
        await ws_manager.send_to(ws, "pong", {})
