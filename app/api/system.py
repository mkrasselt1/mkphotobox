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


@router.get("/system/storage")
def get_storage_status(request: Request, session: Session = Depends(get_session)):
    """Free disk space + estimated remaining photos (public; for the booth)."""
    import os
    cfg = request.app.state.config
    path = cfg["photos"]["storage_path"]
    if not os.path.isdir(path):
        path = "."
    usage = shutil.disk_usage(path)

    # average captured-photo size from the DB; fall back to ~8 MB
    avg = session.exec(select(func.avg(Photo.file_size)).where(Photo.file_size != None)).one()
    avg_bytes = int(avg) if avg else 8 * 1024 * 1024
    # add ~35% headroom for the accompanying GIF/thumbnail
    per_photo = int(avg_bytes * 1.35)

    remaining = int(usage.free / per_photo) if per_photo > 0 else 0
    low = usage.free < 1_000_000_000 or remaining < 30  # <1 GB or <30 shots
    return {
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "avg_photo_bytes": per_photo,
        "photos_remaining": remaining,
        "low": low,
    }


@router.get("/system/admin-access")
def get_admin_access(request: Request, _user=Depends(require_role("admin"))):
    """Current local-only setting + allowed IPs + the caller's IP."""
    admin_cfg = get_config().get("admin", {})
    return {
        "local_only": bool(admin_cfg.get("local_only", False)),
        "allowed_ips": admin_cfg.get("allowed_ips", []) or [],
        "your_ip": request.client.host if request.client else "",
    }


@router.post("/system/admin-access")
def set_admin_access(body: dict, request: Request, _user=Depends(require_role("admin"))):
    """Enable/disable local-only admin + manage allowed IPs (persisted)."""
    from app.config import update_user_config

    local_only = bool(body.get("local_only", False))
    ips = body.get("allowed_ips", []) or []
    if isinstance(ips, str):
        ips = [x.strip() for x in ips.replace("\n", ",").split(",") if x.strip()]

    # Safety: don't let the admin lock themselves out — always keep their IP.
    your_ip = request.client.host if request.client else ""
    if local_only and your_ip and your_ip not in ips and your_ip not in ("127.0.0.1", "::1"):
        ips.append(your_ip)

    update_user_config("admin.local_only", local_only)
    update_user_config("admin.allowed_ips", ips)
    return {"local_only": local_only, "allowed_ips": ips, "your_ip": your_ip}


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
