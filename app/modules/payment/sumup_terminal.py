"""SumUp Card-Terminal payment module.

Sends a payment request to a paired SumUp terminal (Solo / Air)
via the SumUp Terminal API.  Requires internet.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.modules.payment.base import AbstractPayment

logger = logging.getLogger(__name__)

_TERMINAL_URL = "https://api.sumup.com/v0.1/terminals"
_CHECKOUT_URL = "https://api.sumup.com/v0.1/checkouts"
_STATUS_TIMEOUT = 120  # seconds


class SumUpTerminalPayment(AbstractPayment):
    name = "payment.sumup_terminal"

    def __init__(self):
        self._api_key: str = ""
        self._merchant_code: str = ""
        self._terminal_id: str = ""
        self._currency: str = "EUR"
        self._pending: dict[str, dict[str, Any]] = {}

    async def initialize(self, config: dict[str, Any]) -> None:
        self._api_key = config.get("api_key", "")
        self._merchant_code = config.get("merchant_code", "")
        self._terminal_id = config.get("terminal_id", "")
        self._currency = config.get("currency", "EUR")

    async def shutdown(self) -> None:
        self._pending.clear()

    def is_available(self) -> bool:
        return bool(self._api_key and self._merchant_code and self._terminal_id)

    def works_offline(self) -> bool:
        return False

    # ------------------------------------------------------------------

    async def initiate(self, amount_cents: int, reference: str) -> dict[str, Any]:
        """Create a checkout and send it to the paired terminal."""
        import httpx

        headers = {"Authorization": f"Bearer {self._api_key}"}

        # 1. Create checkout
        checkout_body = {
            "checkout_reference": reference,
            "amount": amount_cents / 100,
            "currency": self._currency,
            "merchant_code": self._merchant_code,
            "description": f"Photobox – {reference}",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                _CHECKOUT_URL, json=checkout_body, headers=headers
            )
            resp.raise_for_status()
            checkout = resp.json()

            checkout_id = checkout["id"]

            # 2. Send checkout to terminal
            resp = await client.post(
                f"{_TERMINAL_URL}/{self._terminal_id}/checkout",
                json={"checkout_id": checkout_id},
                headers=headers,
            )
            resp.raise_for_status()

        self._pending[checkout_id] = {
            "created": time.time(),
            "status": "pending",
        }

        logger.info(
            "SumUp Terminal checkout %s sent to terminal %s",
            checkout_id,
            self._terminal_id,
        )
        return {
            "payment_id": checkout_id,
            "status": "pending",
            "terminal_id": self._terminal_id,
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
            logger.exception("SumUp Terminal status check failed for %s", payment_id)
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
                "terminal_id": {
                    "type": "string",
                    "description": "ID des gekoppelten SumUp Terminals",
                },
                "currency": {
                    "type": "string",
                    "default": "EUR",
                    "description": "Währungscode (z.B. EUR)",
                },
            },
            "required": ["api_key", "merchant_code", "terminal_id"],
        }

    def get_status(self) -> dict[str, Any]:
        status = super().get_status()
        status["terminal_id"] = self._terminal_id
        status["pending_count"] = sum(
            1 for p in self._pending.values() if p["status"] == "pending"
        )
        return status
