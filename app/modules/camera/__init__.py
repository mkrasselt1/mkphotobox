"""Camera module manager with separate preview and capture cameras."""

from __future__ import annotations

import logging
from typing import Any

from app.modules.camera.base import AbstractCamera

logger = logging.getLogger(__name__)


class CameraManager:
    """Manages camera modules. Supports separate cameras for preview and capture.

    Example: USB webcam for live preview, DSLR for the actual photo.
    If no separate capture camera is set, the preview camera is used for both.
    """

    def __init__(self):
        self._cameras: dict[str, AbstractCamera] = {}
        self._preview_id: str | None = None
        self._capture_id: str | None = None

    async def load_configured(self, config: dict[str, Any]) -> None:
        from app.modules import load_module

        cameras_cfg = config.get("cameras", {})
        for cam_id, cam_conf in cameras_cfg.items():
            if not isinstance(cam_conf, dict) or not cam_conf.get("enabled"):
                continue
            full_id = f"camera.{cam_id}"
            try:
                module = await load_module(full_id, cam_conf)
                if module.is_available():
                    self._cameras[full_id] = module
                    if self._preview_id is None:
                        self._preview_id = full_id
                    logger.info("Camera loaded: %s", full_id)
                else:
                    logger.warning("Camera not available on this platform: %s", full_id)
            except Exception:
                logger.exception("Failed to load camera: %s", full_id)

    # ── Properties ────────────────────────────────────────────────────

    @property
    def preview_camera(self) -> AbstractCamera | None:
        if self._preview_id:
            return self._cameras.get(self._preview_id)
        return None

    @property
    def capture_camera(self) -> AbstractCamera | None:
        """Returns the capture camera, or falls back to preview camera."""
        cam_id = self._capture_id or self._preview_id
        if cam_id:
            return self._cameras.get(cam_id)
        return None

    @property
    def active_camera(self) -> AbstractCamera | None:
        """Backward compat — returns preview camera."""
        return self.preview_camera

    @property
    def active_id(self) -> str | None:
        return self._preview_id

    @property
    def capture_id(self) -> str | None:
        return self._capture_id

    # ── Listing ───────────────────────────────────────────────────────

    def list_cameras(self) -> list[dict[str, Any]]:
        return [
            {
                "id": cid,
                "preview": cid == self._preview_id,
                "capture": cid == (self._capture_id or self._preview_id),
                **cam.get_status(),
            }
            for cid, cam in self._cameras.items()
        ]

    # ── Switching ─────────────────────────────────────────────────────

    async def switch(self, camera_id: str) -> bool:
        """Set both preview and capture to the same camera."""
        if camera_id in self._cameras:
            self._preview_id = camera_id
            self._capture_id = None  # same as preview
            return True
        return False

    def set_preview(self, camera_id: str) -> bool:
        if camera_id in self._cameras:
            self._preview_id = camera_id
            return True
        return False

    def set_capture(self, camera_id: str | None) -> bool:
        """Set capture camera. None = same as preview."""
        if camera_id is None:
            self._capture_id = None
            return True
        if camera_id in self._cameras:
            self._capture_id = camera_id
            return True
        return False

    async def activate_camera(self, camera_type: str, config: dict[str, Any], role: str = "both") -> str:
        """Load a camera at runtime. role: 'preview', 'capture', or 'both'."""
        from app.modules import load_module

        # Build a unique ID that includes device_index for opencv
        device_index = config.get("device_index")
        full_id = f"camera.{camera_type}"
        if device_index is not None:
            full_id = f"camera.{camera_type}.{device_index}"

        # If this exact camera is already loaded, just reassign the role
        if full_id in self._cameras:
            self._assign_role(full_id, role)
            logger.info("Camera role reassigned: %s -> %s", full_id, role)
            return full_id

        # Load new module
        base_id = f"camera.{camera_type}"
        module = await load_module(base_id, config)
        if not module.is_available():
            raise RuntimeError(f"Camera '{camera_type}' is not available on this platform")

        # If role is 'both', shut down everything. Otherwise only shut down the
        # camera that currently holds the same role.
        if role == "both":
            await self.shutdown_all()
        elif role == "preview" and self._preview_id and self._preview_id != self._capture_id:
            await self._shutdown_camera(self._preview_id)
        elif role == "capture" and self._capture_id and self._capture_id != self._preview_id:
            await self._shutdown_camera(self._capture_id)

        self._cameras[full_id] = module
        self._assign_role(full_id, role)
        logger.info("Camera activated at runtime: %s (role=%s)", full_id, role)
        return full_id

    def _assign_role(self, cam_id: str, role: str) -> None:
        if role == "preview":
            self._preview_id = cam_id
        elif role == "capture":
            self._capture_id = cam_id
        else:  # both
            self._preview_id = cam_id
            self._capture_id = None

    # ── Capture / Preview ─────────────────────────────────────────────

    async def capture(self) -> bytes:
        cam = self.capture_camera
        if cam is None:
            raise RuntimeError("No capture camera configured")
        return await cam.capture()

    async def get_preview_frame(self) -> bytes:
        cam = self.preview_camera
        if cam is None:
            raise RuntimeError("No preview camera configured")
        return await cam.get_preview_frame()

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def _shutdown_camera(self, cam_id: str) -> None:
        cam = self._cameras.pop(cam_id, None)
        if cam:
            try:
                await cam.shutdown()
            except Exception:
                logger.exception("Error shutting down camera %s", cam_id)

    async def shutdown_all(self) -> None:
        for cam in self._cameras.values():
            try:
                await cam.shutdown()
            except Exception:
                logger.exception("Error shutting down camera")
        self._cameras.clear()
        self._preview_id = None
        self._capture_id = None
