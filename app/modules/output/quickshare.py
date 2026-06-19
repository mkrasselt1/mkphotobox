"""QuickShare/AirDrop output — opens system share dialog.

On Android/Chrome: uses Web Share API (triggered from frontend).
On Linux: uses xdg-open or kde-open.
This module mainly exists as a marker so the frontend knows to show the share button.
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.output.base import AbstractOutput

logger = logging.getLogger(__name__)


class QuickShareOutput(AbstractOutput):
    """QuickShare/AirDrop — actual sharing happens client-side via Web Share API."""

    name = "output.quickshare"

    async def initialize(self, config: dict[str, Any]) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def is_available(self) -> bool:
        # Always available — the frontend uses the Web Share API
        return True

    async def send(self, photo_path: str, metadata: dict[str, Any]) -> dict[str, Any]:
        # The actual share is done by the browser's Web Share API.
        # This is a no-op on the server side.
        return {"status": "ok", "message": "Share triggered via Web Share API on client"}
