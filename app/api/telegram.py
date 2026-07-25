"""Telegram notifications — configure the bot, test it, and let the booth send a
help request. Automatic alerts (e.g. printer out of paper) call the service
directly from the relevant flow."""

from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from app.auth import require_role
from app.config import get_config, persist_settings
from app.database import get_session
from app.services.telegram_service import get_telegram

router = APIRouter(prefix="/api/v1/telegram", tags=["telegram"])

_KEYS = ("enabled", "bot_token", "chat_id", "notify_help", "notify_media")


@router.get("/status")
def status(_user=Depends(require_role("admin", "organizer"))):
    return get_telegram().public_status()


@router.post("/configure")
def configure(body: dict, request: Request,
              session: Session = Depends(get_session),
              _user=Depends(require_role("admin"))):
    updates = {}
    for key in _KEYS:
        if key in body:
            # keep the stored token when the field is left blank
            if key == "bot_token" and body.get(key) in (None, ""):
                continue
            updates[f"telegram.{key}"] = body[key]
    persist_settings(session, updates)          # DB + in-memory, survives restart
    svc = get_telegram()
    svc.configure(get_config())
    request.app.state.config = get_config()
    return {"status": "ok", "config": svc.public_status()}


@router.post("/test")
async def test(_user=Depends(require_role("admin"))):
    """Send a test message using the currently configured token/chat."""
    svc = get_telegram()
    return await asyncio.to_thread(
        svc.send, "✅ <b>MKPhotobox</b>: Test — der Telegram-Bot funktioniert.")


@router.post("/help")
async def help_request(request: Request):
    """Public: a guest pressed the help button — notify the operator."""
    svc = get_telegram()
    if not svc.ready or not svc.notify_help_enabled:
        return {"ok": False, "message": "Telegram-Hilfe ist nicht aktiv."}

    event = ""
    try:
        from app.database import get_engine
        from app.models import Event
        with Session(get_engine()) as s:
            e = s.exec(select(Event).where(Event.is_active == True)).first()
            event = e.name if e else ""
    except Exception:
        event = ""

    text = f"🆘 <b>Hilfe angefordert</b> an der Photobox um {datetime.now():%H:%M}."
    if event:
        text += f"\nEvent: {event}"
    # throttle so a row of taps doesn't spam the operator
    res = await asyncio.to_thread(svc.notify_throttled, "help", text, 20.0)
    ok = res.get("ok", False)
    return {"ok": ok, "message": "Hilfe ist unterwegs." if ok else res.get("message", "")}
