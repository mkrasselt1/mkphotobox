"""Module management API endpoints."""

from __future__ import annotations

import importlib
import logging

from fastapi import APIRouter, Depends, Request

from app.auth import require_role
from app.models import User
from app.modules import MODULE_REGISTRY

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/modules", tags=["modules"])

# Human-readable names for known modules
_DISPLAY_NAMES = {
    "camera.gphoto2": "gPhoto2 (DSLR)",
    "camera.digicamcontrol": "digiCamControl (DSLR/Windows)",
    "camera.webrtc": "WebRTC (Browser-Kamera)",
    "camera.opencv": "OpenCV (Webcam)",
    "trigger.touchscreen": "Touchscreen (Browser)",
    "trigger.keyboard": "Tastatur (Browser)",
    "trigger.host_keyboard": "Tastatur/USB-HID (Host)",
    "trigger.gpio": "GPIO (Raspberry Pi)",
    "trigger.acoustic": "Akustik (Mikrofon)",
    "trigger.serial": "Seriell (RS232/USB)",
    "trigger.bluetooth": "Bluetooth-Remote (Host)",
    "output.download": "Download",
    "output.email": "E-Mail (SMTP)",
    "output.printer": "Drucker",
    "output.web_upload": "Web-Upload",
    "output.bluetooth": "Bluetooth",
    "output.quickshare": "QuickShare / AirDrop",
    "output.usb_copy": "USB-Kopie",
    "payment.sumup_qr": "SumUp QR-Code",
    "payment.sumup_terminal": "SumUp Terminal",
}


def _get_category(module_id: str) -> str:
    return module_id.split(".")[0]


# Requirements are a property of the machine, not of a request: they only change
# when someone installs a package, which needs a restart anyway.
_requirement_cache: dict[str, str | None] = {}


def _system_requirement(module_id: str) -> str | None:
    """What this box is missing before `module_id` could run, else None.

    Asks the class, never an instance — system_requirement() is a classmethod
    precisely so listing the modules doesn't open cameras or serial ports.
    """
    if module_id in _requirement_cache:
        return _requirement_cache[module_id]

    reason: str | None
    dotted = MODULE_REGISTRY.get(module_id)
    if not dotted:
        reason = "Unbekanntes Modul"
    else:
        module_path, class_name = dotted.rsplit(":", 1)
        try:
            cls = getattr(importlib.import_module(module_path), class_name)
            reason = cls.system_requirement()
        except ModuleNotFoundError as exc:
            reason = f"Python-Paket fehlt: {exc.name}"
        except Exception as exc:  # a broken module must not break the list
            logger.warning("system_requirement failed for %s", module_id, exc_info=True)
            reason = f"Modul nicht ladbar: {type(exc).__name__}: {exc}"[:200]

    _requirement_cache[module_id] = reason
    return reason


def _build_all_modules(request: Request) -> dict[str, list[dict]]:
    """Build a complete module list: all from registry + config, with loaded status."""
    app = request.app
    cfg = app.state.config

    # Collect loaded module IDs from managers
    loaded_ids = set()
    for cam in app.state.cameras.list_cameras():
        loaded_ids.add(cam.get("id", cam.get("name", "")))
    for trig in app.state.triggers.list_triggers():
        loaded_ids.add(trig.get("name", ""))
    for out in app.state.outputs.list_outputs():
        loaded_ids.add(out.get("name", ""))
    for pay in app.state.payments.list_payments():
        loaded_ids.add(pay.get("id", pay.get("name", "")))

    # Collect all known modules from config sections
    config_sections = {
        "camera": cfg.get("cameras", {}),
        "trigger": cfg.get("triggers", {}),
        "output": cfg.get("outputs", {}),
        "payment": cfg.get("payment", {}),
    }

    result = {"cameras": [], "triggers": [], "outputs": [], "payments": []}
    category_keys = {
        "camera": "cameras",
        "trigger": "triggers",
        "output": "outputs",
        "payment": "payments",
    }

    seen = set()

    for category, section_cfg in config_sections.items():
        for mod_id, mod_conf in section_cfg.items():
            if not isinstance(mod_conf, dict):
                continue
            full_id = f"{category}.{mod_id}"
            if full_id not in MODULE_REGISTRY:
                continue
            seen.add(full_id)

            enabled = mod_conf.get("enabled", False)
            loaded = full_id in loaded_ids
            display_name = _DISPLAY_NAMES.get(full_id, full_id)
            requirement = _system_requirement(full_id)

            result_key = category_keys[category]
            result[result_key].append({
                "id": full_id,
                "short_id": mod_id,
                "name": display_name,
                "enabled": enabled,
                "loaded": loaded,
                # "available" = this box could run it. Distinct from "loaded"
                # (running) and from "enabled" (switched on in the config), so
                # the UI can tell a missing package from a missing tick.
                "available": loaded or requirement is None,
                "requirement": requirement,
                "config": {k: v for k, v in mod_conf.items() if k != "enabled"},
            })

    # Also add registry modules not in config (so nothing is hidden)
    for reg_id in MODULE_REGISTRY:
        if reg_id in seen:
            continue
        category = _get_category(reg_id)
        result_key = category_keys.get(category)
        if not result_key:
            continue
        requirement = _system_requirement(reg_id)
        result[result_key].append({
            "id": reg_id,
            "short_id": reg_id.split(".", 1)[1],
            "name": _DISPLAY_NAMES.get(reg_id, reg_id),
            "enabled": False,
            "loaded": False,
            "available": requirement is None,
            "requirement": requirement,
            "config": {},
        })

    return result


@router.get("/")
def list_modules(
    request: Request,
    _user: User = Depends(require_role("admin")),
):
    """List all modules (loaded and unloaded) with their status."""
    return _build_all_modules(request)


@router.get("/{module_id:path}/config")
def get_module_config(
    module_id: str,
    request: Request,
    _user: User = Depends(require_role("admin")),
):
    """Get the configuration schema for a module."""
    if module_id not in MODULE_REGISTRY:
        return {"error": "Unknown module"}

    # Find in loaded managers
    app = request.app
    managers = [app.state.cameras, app.state.triggers, app.state.outputs, app.state.payments]
    for mgr in managers:
        instances = getattr(mgr, "_cameras", None) or getattr(mgr, "_triggers", None) or \
                    getattr(mgr, "_outputs", None) or getattr(mgr, "_payments", None) or {}
        if module_id in instances:
            mod = instances[module_id]
            return {
                "id": module_id,
                "status": mod.get_status(),
                "config_schema": mod.get_config_schema(),
            }

    return {"id": module_id, "status": {"loaded": False}, "config_schema": {}}
