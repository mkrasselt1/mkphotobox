"""Abstract trigger interface."""

from __future__ import annotations

from abc import abstractmethod
from typing import Callable

from app.modules.base import ModuleBase


class AbstractTrigger(ModuleBase):
    category = "trigger"

    @abstractmethod
    async def start_listening(self, callback: Callable) -> None:
        """Begin listening for trigger events. Call callback() on fire."""
        ...

    @abstractmethod
    async def stop_listening(self) -> None:
        """Stop listening and release resources."""
        ...
