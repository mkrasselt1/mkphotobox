"""Module registry and lazy loader."""

from __future__ import annotations

import importlib
import logging
from typing import Any

from app.modules.base import ModuleBase

logger = logging.getLogger(__name__)

# Explicit registry: module_id -> "dotted.module.path:ClassName"
MODULE_REGISTRY: dict[str, str] = {
    # Camera
    "camera.gphoto2": "app.modules.camera.gphoto2_cam:GPhoto2Camera",
    "camera.digicamcontrol": "app.modules.camera.digicamcontrol:DigiCamCamera",
    "camera.webrtc": "app.modules.camera.webrtc:WebRTCCamera",
    "camera.opencv": "app.modules.camera.opencv_cam:OpenCVCamera",
    # Trigger
    "trigger.acoustic": "app.modules.trigger.acoustic:AcousticTrigger",
    "trigger.gpio": "app.modules.trigger.gpio_trigger:GPIOTrigger",
    "trigger.serial": "app.modules.trigger.serial_trigger:SerialTrigger",
    "trigger.touchscreen": "app.modules.trigger.touchscreen:TouchscreenTrigger",
    "trigger.keyboard": "app.modules.trigger.keyboard:KeyboardTrigger",
    "trigger.bluetooth": "app.modules.trigger.bluetooth_trigger:BluetoothTrigger",
    "trigger.host_keyboard": "app.modules.trigger.host_keyboard:HostKeyboardTrigger",
    # Output
    "output.email": "app.modules.output.email_out:EmailOutput",
    "output.bluetooth": "app.modules.output.bluetooth_out:BluetoothOutput",
    "output.quickshare": "app.modules.output.quickshare:QuickShareOutput",
    "output.printer": "app.modules.output.printer:PrinterOutput",
    "output.usb_copy": "app.modules.output.usb_copy:USBCopyOutput",
    "output.web_upload": "app.modules.output.web_upload:WebUploadOutput",
    "output.download": "app.modules.output.download:DownloadOutput",
    # Payment
    "payment.stripe_qr": "app.modules.payment.stripe_qr:StripeQRPayment",
    "payment.sumup_qr": "app.modules.payment.sumup_qr:SumUpQRPayment",
    "payment.sumup_terminal": "app.modules.payment.sumup_terminal:SumUpTerminalPayment",
    "payment.mdb": "app.modules.payment.mdb:MDBPayment",
}


async def load_module(module_id: str, config: dict[str, Any]) -> ModuleBase:
    """Lazy-import and instantiate a module by its registry ID."""
    dotted_path = MODULE_REGISTRY.get(module_id)
    if dotted_path is None:
        raise ValueError(f"Unknown module: {module_id}")

    module_path, class_name = dotted_path.rsplit(":", 1)
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    instance = cls()
    await instance.initialize(config)
    return instance
