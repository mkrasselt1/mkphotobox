"""Abstract camera interface."""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from typing import AsyncIterator

from app.modules.base import ModuleBase


class AbstractCamera(ModuleBase):
    category = "camera"

    @abstractmethod
    async def capture(self) -> bytes:
        """Capture a full-resolution photo. Returns JPEG bytes."""
        ...

    @abstractmethod
    async def get_preview_frame(self) -> bytes:
        """Return a single JPEG preview frame (low resolution)."""
        ...

    async def stream_preview(self) -> AsyncIterator[bytes]:
        """Async generator yielding JPEG preview frames."""
        while True:
            yield await self.get_preview_frame()
            await asyncio.sleep(1 / 15)  # 15 fps cap for RPi3
