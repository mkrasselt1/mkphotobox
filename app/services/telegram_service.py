"""Telegram notifications — send status/alerts (help calls, printer out of paper,
errors) to a Telegram chat via the Bot API.

Dependency-free (stdlib urllib); ``send`` is blocking, so call it via
asyncio.to_thread from async code. Configure a bot token (@BotFather) and a
chat id in the admin. ``notify`` only fires when enabled; ``notify_throttled``
suppresses repeats of the same alert within a window (so a near-empty printer
doesn't message on every print).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

API = "https://api.telegram.org"


class TelegramNotifier:
    def __init__(self) -> None:
        self._enabled = False
        self._token = ""
        self._chat_id = ""
        self._notify_help = True
        self._notify_media = True
        self._last_sent: dict[str, float] = {}   # throttle key -> monotonic ts

    def configure(self, cfg: dict) -> None:
        tg = (cfg or {}).get("telegram", {}) or {}
        self._enabled = bool(tg.get("enabled"))
        self._token = (tg.get("bot_token") or "").strip()
        self._chat_id = str(tg.get("chat_id") or "").strip()
        self._notify_help = tg.get("notify_help", True) is not False
        self._notify_media = tg.get("notify_media", True) is not False

    @property
    def configured(self) -> bool:
        return bool(self._token and self._chat_id)

    @property
    def ready(self) -> bool:
        return bool(self._enabled and self.configured)

    @property
    def notify_help_enabled(self) -> bool:
        return self._notify_help

    @property
    def notify_media_enabled(self) -> bool:
        return self._notify_media

    def public_status(self) -> dict:
        return {
            "enabled": self._enabled,
            "configured": self.configured,
            "has_token": bool(self._token),
            "chat_id": self._chat_id,
            "notify_help": self._notify_help,
            "notify_media": self._notify_media,
        }

    # ── sending ─────────────────────────────────────────────────────────────
    def send(self, text: str, *, token: Optional[str] = None,
             chat_id: Optional[str] = None) -> dict:
        """Send a message now (ignores the enabled flag — used by the test
        button too). Returns {"ok": bool, "message": str}."""
        tok = (token or self._token).strip()
        chat = str(chat_id or self._chat_id).strip()
        if not tok or not chat:
            return {"ok": False, "message": "Telegram nicht konfiguriert (Token/Chat-ID fehlt)."}
        data = urllib.parse.urlencode({
            "chat_id": chat, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": "true",
        }).encode()
        try:
            req = urllib.request.Request(f"{API}/bot{tok}/sendMessage", data=data, method="POST")
            with urllib.request.urlopen(req, timeout=15) as r:
                body = json.loads(r.read().decode("utf-8"))
            if body.get("ok"):
                return {"ok": True, "message": "gesendet"}
            return {"ok": False, "message": body.get("description", "Telegram-Fehler")}
        except Exception as e:
            logger.warning("telegram send failed: %s", e)
            return {"ok": False, "message": str(e)}

    def notify(self, text: str) -> dict:
        """Send only when enabled + configured (for automatic alerts)."""
        if not self.ready:
            return {"ok": False, "message": "deaktiviert"}
        return self.send(text)

    def notify_throttled(self, key: str, text: str, min_interval_s: float = 600.0) -> dict:
        """Like notify, but at most once per *min_interval_s* for a given key."""
        if not self.ready:
            return {"ok": False, "message": "deaktiviert"}
        now = time.monotonic()
        last = self._last_sent.get(key)
        if last is not None and (now - last) < min_interval_s:
            return {"ok": False, "message": "throttled"}
        self._last_sent[key] = now
        return self.send(text)


_notifier: Optional[TelegramNotifier] = None


def get_telegram() -> TelegramNotifier:
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier()
    return _notifier
