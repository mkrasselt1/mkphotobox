"""Discover available camera devices with human-readable names.

- Windows: Probes DSHOW devices, tests each for a working signal,
  and enriches with PnP device names where possible.
- Linux: /sys/class/video4linux/*/name + v4l2
"""

from __future__ import annotations

import logging
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CameraDevice:
    index: int
    name: str
    device_id: str = ""
    backend: str = ""
    working: bool = True


def discover_cameras(skip_indices: set[int] | None = None) -> list[CameraDevice]:
    system = platform.system()
    if system == "Windows":
        return _discover_windows(skip_indices or set())
    elif system == "Linux":
        return _discover_linux()
    return _discover_opencv_fallback()


def _discover_windows(skip_indices: set[int]) -> list[CameraDevice]:
    devices: list[CameraDevice] = []

    try:
        import cv2
        import numpy as np
    except ImportError:
        return devices

    # Probe each DSHOW device index
    for i in range(10):
        # Skip devices currently held by the server (would fail to open)
        if i in skip_indices:
            devices.append(CameraDevice(
                index=i, name=f"Kamera {i}", device_id=f"index:{i}",
                backend="DSHOW", working=True,
            ))
            continue

        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            continue

        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        backend = cap.getBackendName()

        # Read frames to check if it delivers a real image
        working = False
        for _ in range(15):
            ret, frame = cap.read()
        if ret:
            unique_pixels = len(np.unique(frame.reshape(-1, 3), axis=0))
            working = unique_pixels > 5

        cap.release()

        status = "" if working else " [kein Signal]"
        devices.append(CameraDevice(
            index=i,
            name=f"Kamera {i} ({w}x{h}){status}",
            device_id=f"index:{i}",
            backend=backend,
            working=working,
        ))

    # Try to enrich with PnP names
    _enrich_with_pnp_names(devices)

    return devices


def _enrich_with_pnp_names(devices: list[CameraDevice]) -> None:
    """Try to replace generic 'Kamera N' names with actual PnP device names."""
    pnp_names = _get_pnp_camera_names()
    if not pnp_names:
        return

    # If there's exactly one PnP camera and exactly one working DSHOW device,
    # we can confidently assign the name
    working_devices = [d for d in devices if d.working]

    if len(pnp_names) == 1 and len(working_devices) == 1:
        d = working_devices[0]
        w_h = d.name.split("(")[-1].rstrip(")").strip()
        d.name = f"{pnp_names[0]} ({w_h})"
        return

    if len(pnp_names) == len(devices):
        # Same count — assign in order (best guess)
        for d, name in zip(devices, pnp_names):
            w_h = d.name.split("(")[-1].rstrip(")").strip()
            status = " [kein Signal]" if not d.working else ""
            d.name = f"{name} ({w_h}){status}"
        return

    # If we have more DSHOW devices than PnP names, assign PnP names to working
    # devices first (more likely to be real cameras)
    name_iter = iter(pnp_names)
    for d in working_devices:
        pnp = next(name_iter, None)
        if pnp:
            w_h = d.name.split("(")[-1].rstrip(")").strip()
            d.name = f"{pnp} ({w_h})"


def _get_pnp_camera_names() -> list[str]:
    """Get camera device names from Windows PnP."""
    names = []

    # Camera + Image class devices
    try:
        result = subprocess.run(
            ["powershell.exe", "-Command",
             "Get-PnpDevice -Class Camera,Image -Status OK "
             "| Select-Object -ExpandProperty FriendlyName"],
            capture_output=True, text=True, timeout=10,
        )
        names = [n.strip() for n in result.stdout.strip().splitlines() if n.strip()]
    except Exception:
        pass

    return names


def _discover_linux() -> list[CameraDevice]:
    devices: list[CameraDevice] = []
    v4l_path = Path("/sys/class/video4linux")

    if not v4l_path.exists():
        return _discover_opencv_fallback()

    for dev_dir in sorted(v4l_path.iterdir()):
        name_file = dev_dir / "name"
        index_file = dev_dir / "index"

        if not name_file.exists():
            continue

        name = name_file.read_text().strip()
        dev_name = dev_dir.name

        # Only list capture devices (index 0), skip metadata devices
        try:
            idx = int(index_file.read_text().strip()) if index_file.exists() else 0
            if idx != 0:
                continue
        except ValueError:
            pass

        try:
            device_index = int(dev_name.replace("video", ""))
        except ValueError:
            device_index = len(devices)

        devices.append(CameraDevice(
            index=device_index, name=name, device_id=f"/dev/{dev_name}", backend="v4l2",
        ))

    return devices or _discover_opencv_fallback()


def _discover_opencv_fallback() -> list[CameraDevice]:
    devices: list[CameraDevice] = []
    try:
        import cv2
    except ImportError:
        return devices

    for i in range(10):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            devices.append(CameraDevice(
                index=i, name=f"Kamera {i} ({w}x{h})", device_id=f"index:{i}",
            ))
        else:
            cap.release()

    return devices
