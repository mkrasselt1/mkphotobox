"""System information and health check API endpoints."""

from __future__ import annotations

import os
import platform
import shutil
import signal
import sys
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session, func, select

from app.auth import require_role
from app.config import get_config, get_nested
from app.database import get_session
from app.i18n import get_all_translations, get_available_locales
from app.models import Photo, User

router = APIRouter(prefix="/api/v1", tags=["system"])

_start_time = time.time()


@router.get("/system/share-base")
def get_share_base(request: Request):
    """Base URL a guest's phone can use to reach this booth (for QR codes).

    The kiosk browser runs on localhost, which is useless in a QR code — so we
    return the box's LAN IP (or a configured override) plus the server port.
    """
    cfg = request.app.state.config
    override = get_nested(cfg, "share.base_url", "") or ""
    if override:
        return {"base_url": override.rstrip("/")}

    import socket
    ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    port = cfg.get("server", {}).get("port", 8080)
    return {"base_url": f"http://{ip}:{port}"}


@router.get("/system/info")
def get_system_info(
    request: Request,
    session: Session = Depends(get_session),
    _user=Depends(require_role("admin")),
):
    cfg = request.app.state.config
    disk = shutil.disk_usage(cfg["photos"]["storage_path"])
    photos_count = session.exec(select(func.count(Photo.id))).one()

    return {
        "version": "0.1.0",
        "platform": platform.platform(),
        "python_version": sys.version,
        "disk_free_mb": disk.free // (1024 * 1024),
        "disk_total_mb": disk.total // (1024 * 1024),
        "photos_count": photos_count,
        "uptime_seconds": round(time.time() - _start_time, 1),
        "ws_connections": request.app.state.ws_manager.count,
    }


@router.get("/system/health")
def health_check(request: Request):
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - _start_time, 1),
        "cameras": request.app.state.cameras.list_cameras(),
    }


@router.post("/system/restart")
def restart_server(_user=Depends(require_role("admin"))):
    """Restart the server process. The process manager should auto-restart it."""
    import threading

    def _do_restart():
        time.sleep(0.5)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=_do_restart, daemon=True).start()
    return {"status": "restarting"}


@router.get("/display/config")
def get_display_config():
    """Return public display settings (no auth required)."""
    cfg = get_config()
    return {
        "preview_size": get_nested(cfg, "display.preview_size", "medium"),
        "gallery_enabled": get_nested(cfg, "gallery.enabled", True),
        "gallery_delete_mode": get_nested(cfg, "gallery.delete_mode", "off"),
        "gallery_delete_recent_minutes": get_nested(cfg, "gallery.delete_recent_minutes", 5),
    }


@router.get("/i18n/{lang}")
def get_translations(lang: str):
    """Return all translation strings for a language."""
    translations = get_all_translations(lang)
    if not translations:
        return {"error": f"Unknown locale: {lang}", "available": get_available_locales()}
    return translations


@router.get("/i18n")
def get_locales():
    """Return list of available locales."""
    return {"locales": get_available_locales()}
