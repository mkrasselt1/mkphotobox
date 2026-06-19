"""Email output — sends photo as attachment via SMTP."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from app.modules.output.base import AbstractOutput

logger = logging.getLogger(__name__)


class EmailOutput(AbstractOutput):
    name = "output.email"

    def __init__(self):
        self._smtp_host = ""
        self._smtp_port = 587
        self._smtp_user = ""
        self._smtp_pass = ""
        self._from_address = ""

    async def initialize(self, config: dict[str, Any]) -> None:
        self._smtp_host = config.get("smtp_host", "")
        self._smtp_port = config.get("smtp_port", 587)
        self._smtp_user = config.get("smtp_user", "")
        self._smtp_pass = config.get("smtp_pass", "")
        self._from_address = config.get("from_address", self._smtp_user)

    async def shutdown(self) -> None:
        pass

    def is_available(self) -> bool:
        return bool(self._smtp_host)

    def requires_network(self) -> bool:
        return True

    async def send(self, photo_path: str, metadata: dict[str, Any]) -> dict[str, Any]:
        to_email = metadata.get("target", "")
        if not to_email:
            return {"status": "error", "message": "No email address provided"}

        return await asyncio.to_thread(self._send_sync, photo_path, to_email)

    def _send_sync(self, photo_path: str, to_email: str) -> dict[str, Any]:
        try:
            msg = MIMEMultipart()
            msg["From"] = self._from_address
            msg["To"] = to_email
            msg["Subject"] = "Dein Photobox-Foto"

            msg.attach(MIMEText("Hier ist dein Foto von der Photobox!", "plain", "utf-8"))

            photo = Path(photo_path)
            if photo.exists():
                with open(photo, "rb") as f:
                    img = MIMEImage(f.read(), name=photo.name)
                    msg.attach(img)

            with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=30) as server:
                server.starttls()
                if self._smtp_user:
                    server.login(self._smtp_user, self._smtp_pass)
                server.send_message(msg)

            logger.info("Email sent to %s", to_email)
            return {"status": "ok", "email": to_email}

        except Exception as e:
            logger.exception("Email send failed")
            return {"status": "error", "message": str(e)}

    def get_config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "smtp_host": {"type": "string", "description": "SMTP server hostname"},
                "smtp_port": {"type": "integer", "default": 587},
                "smtp_user": {"type": "string"},
                "smtp_pass": {"type": "string", "format": "password"},
                "from_address": {"type": "string", "format": "email"},
            },
            "required": ["smtp_host"],
        }
