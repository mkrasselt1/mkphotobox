"""Payment module manager."""

from __future__ import annotations

import logging
from typing import Any

from app.modules.payment.base import AbstractPayment

logger = logging.getLogger(__name__)


class PaymentManager:
    """Manages active payment modules and session credit."""

    def __init__(self):
        self._payments: dict[str, AbstractPayment] = {}
        self._active: str | None = None
        self._prices: dict[str, int] = {}
        # Session credit: overpayment that can be used for further actions
        self._credit_cents: int = 0
        # Currently active payment tracking (for live progress)
        self._current_payment: dict[str, Any] | None = None
        self._bus = None

    def set_bus(self, bus) -> None:
        """Wire up the event bus for broadcasting payment progress."""
        self._bus = bus

    async def load_configured(self, config: dict[str, Any]) -> None:
        from app.modules import load_module

        if not config.get("payment", {}).get("enabled"):
            logger.info("Payment system disabled")
            return

        payment_cfg = config.get("payment", {})
        self._prices = payment_cfg.get("prices", {})

        for pay_id in ("stripe_qr", "sumup_qr", "sumup_terminal", "mdb"):
            pay_conf = payment_cfg.get(pay_id, {})
            if not isinstance(pay_conf, dict) or not pay_conf.get("enabled"):
                continue
            full_id = f"payment.{pay_id}"
            try:
                module = await load_module(full_id, pay_conf)
                if module.is_available():
                    self._payments[full_id] = module
                    if self._active is None:
                        self._active = full_id
                    logger.info("Payment loaded: %s", full_id)
                else:
                    logger.warning("Payment not available: %s", full_id)
            except Exception:
                logger.exception("Failed to load payment: %s", full_id)

    @property
    def is_enabled(self) -> bool:
        return len(self._payments) > 0

    @property
    def credit_cents(self) -> int:
        return self._credit_cents

    def get_price(self, action: str) -> int:
        """Return the price in cents for the given action (capture, print, gif, collage).

        Falls back to ``default_amount_cents`` from the global payment config
        if the action is not explicitly configured.
        """
        from app.config import get_config

        if action in self._prices:
            return int(self._prices[action])

        return int(get_config().get("payment", {}).get("default_amount_cents", 200))

    def get_effective_price(self, action: str) -> int:
        """Price minus available credit (never negative)."""
        return max(0, self.get_price(action) - self._credit_cents)

    def use_credit(self, amount_cents: int) -> int:
        """Deduct up to *amount_cents* from credit. Returns amount actually deducted."""
        deducted = min(self._credit_cents, amount_cents)
        self._credit_cents -= deducted
        return deducted

    def add_credit(self, amount_cents: int) -> None:
        """Add credit (e.g. from overpayment)."""
        self._credit_cents += amount_cents
        logger.info("Credit updated: +%d ct → %d ct total", amount_cents, self._credit_cents)

    def reset_credit(self) -> None:
        """Reset credit (e.g. when session ends)."""
        self._credit_cents = 0

    def list_payments(self) -> list[dict[str, Any]]:
        return [
            {"id": pid, "active": pid == self._active, **pay.get_status()}
            for pid, pay in self._payments.items()
        ]

    async def initiate(
        self,
        amount_cents: int,
        reference: str,
        module_id: str | None = None,
        action: str | None = None,
    ) -> dict:
        pay_id = module_id or self._active
        if pay_id is None or pay_id not in self._payments:
            return {"status": "error", "message": "No payment module available"}

        # Use action-based price when no explicit amount was supplied
        if action and amount_cents == 0:
            amount_cents = self.get_price(action)

        # Apply available credit
        credit_used = self.use_credit(amount_cents)
        remaining = amount_cents - credit_used

        if remaining <= 0:
            # Fully covered by credit
            logger.info("Payment for %s covered by credit (%d ct)", action or reference, credit_used)
            return {
                "payment_id": f"credit_{reference}",
                "status": "completed",
                "amount_cents": amount_cents,
                "credit_used": credit_used,
                "paid_cents": 0,
            }

        # Track the current payment for progress updates
        self._current_payment = {
            "action": action,
            "reference": reference,
            "required_cents": remaining,
            "paid_cents": 0,
            "credit_used": credit_used,
            "original_amount": amount_cents,
        }

        result = await self._payments[pay_id].initiate(remaining, reference)
        result["credit_used"] = credit_used
        result["original_amount"] = amount_cents
        return result

    async def report_cash_inserted(self, amount_cents: int) -> dict[str, Any]:
        """Called by MDB/cash modules when coins or bills are inserted.

        Broadcasts a ``payment.progress`` event via the event bus so the
        booth UI can update in real time.  When the required amount is
        reached the payment is completed and any overpayment becomes credit.
        """
        cp = self._current_payment
        if cp is None:
            # No payment in progress — add directly to credit
            self.add_credit(amount_cents)
            progress = {
                "inserted_cents": amount_cents,
                "paid_cents": 0,
                "required_cents": 0,
                "remaining_cents": 0,
                "credit_cents": self._credit_cents,
                "status": "credit",
            }
            if self._bus:
                await self._bus.emit("payment.progress", progress)
            return progress

        cp["paid_cents"] += amount_cents
        remaining = cp["required_cents"] - cp["paid_cents"]
        status = "pending"

        if remaining <= 0:
            overpayment = abs(remaining)
            if overpayment > 0:
                self.add_credit(overpayment)
                logger.info("Overpayment: %d ct added as credit", overpayment)
            remaining = 0
            status = "completed"

        progress = {
            "action": cp["action"],
            "inserted_cents": amount_cents,
            "paid_cents": cp["paid_cents"],
            "required_cents": cp["required_cents"],
            "remaining_cents": max(0, remaining),
            "credit_cents": self._credit_cents,
            "credit_used": cp["credit_used"],
            "status": status,
        }

        if self._bus:
            await self._bus.emit("payment.progress", progress)

        if status == "completed":
            if self._bus:
                await self._bus.emit("payment.completed", {
                    "action": cp["action"],
                    "amount_cents": cp["original_amount"],
                    "paid_cents": cp["paid_cents"],
                    "credit_used": cp["credit_used"],
                    "credit_remaining": self._credit_cents,
                })
            self._current_payment = None

        return progress

    async def check_status(self, payment_id: str, module_id: str | None = None) -> str:
        pay_id = module_id or self._active
        if pay_id is None or pay_id not in self._payments:
            return "error"
        return await self._payments[pay_id].check_status(payment_id)

    async def shutdown_all(self) -> None:
        for pay in self._payments.values():
            try:
                await pay.shutdown()
            except Exception:
                logger.exception("Error shutting down payment")
        self._payments.clear()
        self._active = None
        self._credit_cents = 0
        self._current_payment = None
