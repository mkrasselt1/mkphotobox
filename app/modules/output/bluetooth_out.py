"""Bluetooth output — sends a photo to a paired phone via OBEX Object Push.

The heavy lifting lives in :mod:`app.services.bluetooth_service`, which is also
what the admin Bluetooth page uses, so sending and the pairing UI can never
disagree about what the box supports.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.modules.output.base import AbstractOutput
from app.services import bluetooth_service

logger = logging.getLogger(__name__)


class BluetoothOutput(AbstractOutput):
    name = "output.bluetooth"

    def __init__(self):
        self._default_address = ""

    async def initialize(self, config: dict[str, Any]) -> None:
        # Optional fixed target (e.g. a staff tablet). Guests normally pass
        # their own address per photo instead.
        self._default_address = (config.get("device") or "").strip()

    async def shutdown(self) -> None:
        pass

    @classmethod
    def system_requirement(cls) -> str | None:
        return bluetooth_service.system_requirement()

    def is_available(self) -> bool:
        return bluetooth_service.available()

    def get_config_schema(self) -> dict:
        return {
            "device": {
                "type": "string",
                "title": "Feste Zieladresse (optional)",
                "description": "MAC-Adresse eines gekoppelten Geräts. Leer lassen, "
                               "damit Gäste ihr eigenes Handy auswählen.",
                "default": "",
            },
        }

    async def send(self, photo_path: str, metadata: dict[str, Any]) -> dict[str, Any]:
        # "target" is the generic destination /outputs/send passes through (the
        # same field the e-mail module reads as the address).
        address = (metadata.get("target")
                   or metadata.get("bluetooth_address")
                   or self._default_address or "").strip()
        if not address:
            return {"status": "error",
                    "message": "Kein Bluetooth-Ziel angegeben — Gerät auswählen oder "
                               "eine feste Adresse konfigurieren"}
        return await asyncio.to_thread(bluetooth_service.send_file, address, photo_path)
