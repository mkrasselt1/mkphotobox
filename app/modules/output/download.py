"""Direct download output — always available."""

from __future__ import annotations

from typing import Any

from app.modules.output.base import AbstractOutput


class DownloadOutput(AbstractOutput):
    name = "output.download"

    async def initialize(self, config: dict[str, Any]) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def is_available(self) -> bool:
        return True

    async def send(self, photo_path: str, metadata: dict[str, Any]) -> dict[str, Any]:
        # Download is handled by the API endpoint directly.
        # This module exists so the UI knows download is available.
        return {"status": "ok", "path": photo_path}
