"""Trigger module manager."""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.modules.trigger.base import AbstractTrigger

logger = logging.getLogger(__name__)


class TriggerManager:
    """Manages active trigger modules."""

    def __init__(self):
        self._triggers: dict[str, AbstractTrigger] = {}

    async def load_configured(self, config: dict[str, Any], callback: Callable) -> None:
        from app.modules import load_module

        triggers_cfg = config.get("triggers", {})
        for trig_id, trig_conf in triggers_cfg.items():
            if not isinstance(trig_conf, dict) or not trig_conf.get("enabled"):
                continue
            full_id = f"trigger.{trig_id}"
            try:
                module = await load_module(full_id, trig_conf)
                if module.is_available():
                    self._triggers[full_id] = module
                    await module.start_listening(callback)
                    logger.info("Trigger loaded: %s", full_id)
                else:
                    logger.warning("Trigger not available: %s", full_id)
            except Exception:
                logger.exception("Failed to load trigger: %s", full_id)

    def list_triggers(self) -> list[dict[str, Any]]:
        return [trig.get_status() for trig in self._triggers.values()]

    async def shutdown_all(self) -> None:
        for trig in self._triggers.values():
            try:
                await trig.stop_listening()
                await trig.shutdown()
            except Exception:
                logger.exception("Error shutting down trigger")
        self._triggers.clear()
