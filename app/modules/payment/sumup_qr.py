"""SumUp QR-Code payment module.

Creates a SumUp checkout via the API and generates a QR code
that the customer scans to pay on their phone.  Requires internet.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.modules.payment.base import AbstractPayment

logger = logging.getLogger(__name__)

_CHECKOUT_URL = "https://api.sumup.com/v0.1/checkouts"
_STATUS_POLL_INTERVAL = 2  # seconds
_STATUS_TIMEOUT = 120  # seconds


class SumUpQRPayment(AbstractPayment):
    name = "payment.sumup_qr"

    def __init__(self):
        self._api_key: str = ""
        self._merchant_code: str = ""
        self._currency: str = "EUR"
        self._pending: dict[str, dict[str, Any]] = {}

    async def initialize(self, config: dict[str, Any]) -> None:
        self._api_key = config.get("api_key", "")
        self._merchant_code = config.get("merchant_code", "")
        self._currency = config.get("currency", "EUR")

    async def shutdown(self) -> None:
        self._pending.clear()

    def is_available(self) -> bool:
        return bool(self._api_key and self._merchant_code)

    def works_offline(self) -> bool:
        return False

    # ------------------------------------------------------------------

    async def initiate(self, amount_cents: int, reference: str) -> dict[str, Any]:
        """Create a SumUp checkout and return its QR payload."""
        import httpx

        body = {
            "checkout_reference": reference,
            "amount": amount_cents / 100,
            "currency": self._currency,
            "merchant_code": self._merchant_code,
            "description": f"Photobox – {reference}",
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(_CHECKOUT_URL, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        checkout_id = data["id"]
        self._pending[checkout_id] = {
            "created": time.time(),
            "status": "pending",
        }

        logger.info("SumUp QR checkout created: %s", checkout_id)
        return {
            "payment_id": checkout_id,
            "status": "pending",
            "qr_data": f"https://api.sumup.com/v0.1/checkouts/{checkout_id}/pay",
        }

    async def check_status(self, payment_id: str) -> str:
        import httpx

        entry = self._pending.get(payment_id)
        if entry is None:
            return "failed"

        if time.time() - entry["created"] > _STATUS_TIMEOUT:
            entry["status"] = "timeout"
            return "timeout"

        if entry["status"] in ("completed", "failed", "timeout"):
            return entry["status"]

        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_CHECKOUT_URL}/{payment_id}", headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.exception("SumUp QR status check failed for %s", payment_id)
            return "pending"

        sumup_status = data.get("status", "").upper()
        if sumup_status == "PAID":
            entry["status"] = "completed"
            return "completed"
        if sumup_status == "FAILED":
            entry["status"] = "failed"
            return "failed"
        return "pending"

    # ------------------------------------------------------------------

    def get_config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "api_key": {
                    "type": "string",
                    "description": "SumUp API-Key (Bearer-Token)",
                },
                "merchant_code": {
                    "type": "string",
                    "description": "SumUp Merchant Code",
                },
                "currency": {
                    "type": "string",
                    "default": "EUR",
                    "description": "Währungscode (z.B. EUR)",
                },
            },
            "required": ["api_key", "merchant_code"],
        }

    def get_status(self) -> dict[str, Any]:
        status = super().get_status()
        status["pending_count"] = sum(
            1 for p in self._pending.values() if p["status"] == "pending"
        )
        return status
