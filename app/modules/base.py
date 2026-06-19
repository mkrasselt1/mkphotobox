"""Abstract base class for all photobox modules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ModuleBase(ABC):
    """Base for all photobox modules (cameras, triggers, outputs, payments)."""

    name: str = ""
    category: str = ""  # camera | trigger | output | payment

    @abstractmethod
    async def initialize(self, config: dict[str, Any]) -> None:
        """Called once at startup. Acquire resources lazily."""
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Release all resources."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Fast probe: can this module work on current platform/hardware?"""
        ...

    def get_config_schema(self) -> dict:
        """Return JSON Schema for this module's configurable settings."""
        return {}

    def get_status(self) -> dict[str, Any]:
        """Return current status for admin dashboard."""
        return {"name": self.name, "available": self.is_available()}
