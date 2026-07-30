"""Abstract base class for all photobox modules."""

from __future__ import annotations

import importlib.util
import shutil
from abc import ABC, abstractmethod
from typing import Any


def missing_python_package(package: str, hint: str) -> str | None:
    """Return an operator-facing message if `package` can't be imported.

    Uses find_spec rather than a real import: probing must not execute module
    code (importing cv2 or gphoto2 is slow and touches hardware).
    """
    try:
        if importlib.util.find_spec(package) is not None:
            return None
    except (ImportError, ValueError):
        pass
    return f"Python-Paket '{package}' fehlt — {hint}"


def missing_binary(binaries: list[str], hint: str) -> str | None:
    """Return a message unless at least one of `binaries` is on PATH."""
    if any(shutil.which(b) for b in binaries):
        return None
    return f"{' oder '.join(binaries)} nicht installiert — {hint}"


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
        """Fast probe: can this module work on current platform/hardware?

        The managers call this AFTER initialize() and use it as the load gate,
        so it may legitimately also require configuration (an SMTP host, an API
        key). That makes it unsuitable for answering "could this box run the
        module at all?" — use system_requirement() for that.
        """
        ...

    @classmethod
    def system_requirement(cls) -> str | None:
        """What this machine is missing before the module could work at all.

        Config-independent on purpose: platform, system binaries, Python
        packages. Returns None when nothing is missing. A classmethod so the
        admin UI can ask without constructing (and thus without touching
        cameras, serial ports or GPIO).

        The string is shown to the operator, so name the fix, e.g.
        "obexftp fehlt — sudo apt install bluez-tools".
        """
        return None

    def get_config_schema(self) -> dict:
        """Return JSON Schema for this module's configurable settings."""
        return {}

    def get_status(self) -> dict[str, Any]:
        """Return current status for admin dashboard."""
        return {"name": self.name, "available": self.is_available()}
