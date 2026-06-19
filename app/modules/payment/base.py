"""Abstract payment interface."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from app.modules.base import ModuleBase


class AbstractPayment(ModuleBase):
    category = "payment"

    @abstractmethod
    async def initiate(self, amount_cents: int, reference: str) -> dict[str, Any]:
        """Start a payment. Returns {"payment_id": ..., "status": ..., ...}."""
        ...

    @abstractmethod
    async def check_status(self, payment_id: str) -> str:
        """Returns "pending" | "completed" | "failed" | "timeout"."""
        ...

    def works_offline(self) -> bool:
        """Override to False for payments that require internet."""
        return True
