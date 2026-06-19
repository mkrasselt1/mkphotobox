"""Abstract output interface."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from app.modules.base import ModuleBase


class AbstractOutput(ModuleBase):
    category = "output"

    @abstractmethod
    async def send(self, photo_path: str, metadata: dict[str, Any]) -> dict[str, Any]:
        """Deliver a photo. Returns {"status": "ok"|"queued"|"error", ...}."""
        ...

    def requires_network(self) -> bool:
        """Override to True for outputs that need internet."""
        return False
