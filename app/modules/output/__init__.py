"""Output module manager."""

from __future__ import annotations

import logging
from typing import Any

from app.modules.output.base import AbstractOutput

logger = logging.getLogger(__name__)


class OutputManager:
    """Manages active output modules."""

    def __init__(self):
        self._outputs: dict[str, AbstractOutput] = {}

    async def load_configured(self, config: dict[str, Any]) -> None:
        from app.modules import load_module

        outputs_cfg = config.get("outputs", {})
        for out_id, out_conf in outputs_cfg.items():
            if not isinstance(out_conf, dict) or not out_conf.get("enabled"):
                continue
            full_id = f"output.{out_id}"
            try:
                module = await load_module(full_id, out_conf)
                if module.is_available():
                    self._outputs[full_id] = module
                    logger.info("Output loaded: %s", full_id)
                else:
                    logger.warning("Output not available: %s", full_id)
            except Exception:
                logger.exception("Failed to load output: %s", full_id)

    def list_outputs(self) -> list[dict[str, Any]]:
        return [
            {**out.get_status(), "requires_network": out.requires_network()}
            for out in self._outputs.values()
        ]

    def get_available_outputs(self) -> dict[str, AbstractOutput]:
        return dict(self._outputs)

    async def reload_output(self, full_id: str, out_conf: dict[str, Any]) -> bool:
        """(Re)load a single output after its config changed at runtime.

        Returns True if the module is now loaded and available.
        """
        from app.modules import load_module

        existing = self._outputs.pop(full_id, None)
        if existing is not None:
            try:
                await existing.shutdown()
            except Exception:
                logger.exception("Error shutting down %s", full_id)

        if not out_conf.get("enabled"):
            logger.info("Output disabled: %s", full_id)
            return False

        try:
            module = await load_module(full_id, out_conf)
            if module.is_available():
                self._outputs[full_id] = module
                logger.info("Output (re)loaded: %s", full_id)
                return True
            logger.warning("Output not available after reload: %s", full_id)
        except Exception:
            logger.exception("Failed to reload output: %s", full_id)
        return False

    async def send(self, module_id: str, photo_path: str, metadata: dict) -> dict:
        output = self._outputs.get(module_id)
        if output is None:
            return {"status": "error", "message": f"Output '{module_id}' not available"}
        return await output.send(photo_path, metadata)

    async def shutdown_all(self) -> None:
        for out in self._outputs.values():
            try:
                await out.shutdown()
            except Exception:
                logger.exception("Error shutting down output")
        self._outputs.clear()
