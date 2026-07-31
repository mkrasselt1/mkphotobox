"""System information and health check API endpoints."""

from __future__ import annotations

import os
import platform
import shutil
import signal
import sys
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
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


def _pending_print_jobs() -> list[str]:
    import subprocess
    try:
        r = subprocess.run(["lpstat", "-o"], capture_output=True, text=True, timeout=8)
        return [ln for ln in r.stdout.splitlines() if ln.strip()]
    except Exception:
        return []


@router.get("/system/shutdown-check")
def shutdown_check(_user=Depends(require_role("admin"))):
    """Pre-shutdown status: any pending print jobs? + whether power sudo works."""
    jobs = _pending_print_jobs()
    return {"pending_jobs": len(jobs), "jobs": jobs[:20],
            "can_power": _can_sudo(SYSTEMCTL, "poweroff")}


SYSTEMCTL = "/usr/bin/systemctl"


def _can_sudo(*cmd: str) -> bool:
    """True if the app user may run *cmd* via sudo without a password. Uses
    ``sudo -n -l`` so it checks the actual permission (not a generic ``sudo -n
    true``, which only passes thanks to an unrelated cached credential)."""
    import subprocess
    try:
        r = subprocess.run(["sudo", "-n", "-l", *cmd], capture_output=True, timeout=8)
        return r.returncode == 0
    except Exception:
        return False


def _power_action(action: str) -> dict:
    """Run systemctl poweroff/reboot via sudo (needs the NOPASSWD sudoers rule
    that setup.sh installs). Delayed slightly so the HTTP response is sent."""
    import subprocess
    import threading
    import time as _t

    if not _can_sudo(SYSTEMCTL, action):
        return {"status": "error",
                "message": "Keine Berechtigung zum Herunterfahren/Neustarten — "
                           "sudoers-Regel fehlt (scripts/setup.sh erneut ausführen)."}

    def _run():
        _t.sleep(1)
        subprocess.run(["sudo", "-n", SYSTEMCTL, action], capture_output=True)

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "ok", "action": action}


@router.post("/system/shutdown")
def shutdown(body: dict | None = None, _user=Depends(require_role("admin"))):
    """Shut the box down — refuses if print jobs are pending (unless force)."""
    body = body or {}
    jobs = _pending_print_jobs()
    if jobs and not body.get("force"):
        raise HTTPException(status_code=409,
                            detail=f"{len(jobs)} Druckauftrag/-aufträge offen — abwarten oder 'force'.")
    res = _power_action("poweroff")
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res["message"])
    return {"status": "shutting_down", "pending_jobs": len(jobs), "forced": bool(body.get("force"))}


@router.post("/system/reboot")
def reboot(body: dict | None = None, _user=Depends(require_role("admin"))):
    """Reboot the box — refuses if print jobs are pending (unless force)."""
    body = body or {}
    jobs = _pending_print_jobs()
    if jobs and not body.get("force"):
        raise HTTPException(status_code=409,
                            detail=f"{len(jobs)} Druckauftrag/-aufträge offen — abwarten oder 'force'.")
    res = _power_action("reboot")
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res["message"])
    return {"status": "rebooting", "pending_jobs": len(jobs), "forced": bool(body.get("force"))}


# ── Self-update (git pull + restart) ─────────────────────────────────────────

SERVICE_NAME = "mkphotobox.service"


def _repo_dir() -> Path:
    """The app's git working tree (app/api/system.py -> repo root)."""
    return Path(__file__).resolve().parents[2]


@router.get("/system/update-check")
def update_check(_user=Depends(require_role("admin"))):
    """Report current commit + whether a self-update is possible (git + sudo)."""
    import subprocess
    repo = _repo_dir()
    is_git = (repo / ".git").is_dir()
    head = ""
    if is_git:
        try:
            head = subprocess.run(["git", "log", "--oneline", "-1"], cwd=str(repo),
                                  capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            head = ""
    return {"is_git": is_git, "head": head,
            "can_restart": _can_sudo(SYSTEMCTL, "restart", SERVICE_NAME)}


@router.post("/system/update")
def system_update(_user=Depends(require_role("admin"))):
    """Pull the latest code from git and restart the service.

    Runs as the app user (which owns the checkout) — only the restart needs the
    NOPASSWD sudoers rule. The DB schema auto-migrates on startup."""
    import subprocess
    import threading
    import time as _t

    repo = _repo_dir()
    if not (repo / ".git").is_dir():
        raise HTTPException(status_code=400,
                            detail="Kein git-Repo — Update über scripts/update.sh ausführen.")

    def git(*a, timeout=120):
        return subprocess.run(["git", *a], cwd=str(repo),
                              capture_output=True, text=True, timeout=timeout)

    try:
        before = git("rev-parse", "--short", "HEAD").stdout.strip()
        branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "main"
        f = git("fetch", "origin", branch)
        if f.returncode != 0:
            raise HTTPException(status_code=502, detail=f"git fetch fehlgeschlagen: {f.stderr.strip()[:200]}")
        r = git("reset", "--hard", f"origin/{branch}")
        if r.returncode != 0:
            raise HTTPException(status_code=500, detail=f"git reset fehlgeschlagen: {r.stderr.strip()[:200]}")
        after = git("rev-parse", "--short", "HEAD").stdout.strip()
        head = git("log", "--oneline", "-1").stdout.strip()
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Update-Timeout (Netzwerk?).")

    changed = before != after
    restarting = False
    if changed:
        if not _can_sudo(SYSTEMCTL, "restart", SERVICE_NAME):
            return {"status": "updated_no_restart", "changed": True,
                    "before": before, "after": after, "head": head,
                    "message": "Aktualisiert, aber Neustart nicht erlaubt (sudoers-Regel fehlt). "
                               "Bitte Dienst manuell neu starten."}
        # clear bytecode caches, then restart (the service relaunches itself)
        for pyc in repo.glob("app/**/__pycache__"):
            shutil.rmtree(pyc, ignore_errors=True)

        def _restart():
            _t.sleep(1.5)
            subprocess.run(["sudo", "-n", SYSTEMCTL, "restart", SERVICE_NAME], capture_output=True)

        threading.Thread(target=_restart, daemon=True).start()
        restarting = True

    return {"status": "ok", "changed": changed, "before": before, "after": after,
            "head": head, "restarting": restarting}


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


@router.get("/system/network")
def get_network(_user=Depends(require_role("admin"))):
    """Network status: interfaces + IPs, default gateway, internet reachability,
    and Tailscale state. Best-effort — every probe is wrapped so a missing tool
    never breaks the whole response."""
    import json
    import socket
    import subprocess

    info = {
        "hostname": socket.gethostname(),
        "interfaces": [],
        "gateway": "",
        "internet": False,
        "tailscale": {"available": False},
    }

    # ── interfaces (IPv4) ──────────────────────────────────────────────
    try:
        r = subprocess.run(["ip", "-j", "-4", "addr"], capture_output=True, text=True, timeout=8)
        for iface in json.loads(r.stdout or "[]"):
            name = iface.get("ifname")
            if name == "lo":
                continue
            addrs = [a.get("local") for a in iface.get("addr_info", []) if a.get("local")]
            if not addrs and iface.get("operstate") != "UP":
                continue
            info["interfaces"].append({
                "name": name,
                "state": iface.get("operstate", ""),
                "addresses": addrs,
            })
    except Exception:
        # fallback: just the primary outbound IP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            info["interfaces"].append({"name": "?", "state": "UP", "addresses": [s.getsockname()[0]]})
            s.close()
        except Exception:
            pass

    # ── default gateway ────────────────────────────────────────────────
    try:
        r = subprocess.run(["ip", "-j", "route", "show", "default"],
                           capture_output=True, text=True, timeout=8)
        routes = json.loads(r.stdout or "[]")
        if routes:
            info["gateway"] = routes[0].get("gateway", "")
    except Exception:
        pass

    # ── internet reachability (quick TCP to a public DNS) ──────────────
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.5)
        s.connect(("1.1.1.1", 53))
        s.close()
        info["internet"] = True
    except Exception:
        info["internet"] = False

    # ── Tailscale ──────────────────────────────────────────────────────
    try:
        r = subprocess.run(["tailscale", "status", "--json"],
                           capture_output=True, text=True, timeout=8)
        ts = json.loads(r.stdout or "{}")
        self_ = ts.get("Self", {}) or {}
        peers = (ts.get("Peer") or {}).values()
        info["tailscale"] = {
            "available": True,
            "backend_state": ts.get("BackendState", ""),   # "Running" when connected
            "self_ip": (self_.get("TailscaleIPs") or [""])[0],
            "hostname": self_.get("HostName", ""),
            "dns_name": (self_.get("DNSName", "") or "").rstrip("."),
            "online": bool(self_.get("Online", False)),
            "peers_total": len(list(peers)),
            "peers_online": sum(1 for p in (ts.get("Peer") or {}).values() if p.get("Online")),
        }
    except FileNotFoundError:
        info["tailscale"] = {"available": False, "reason": "Tailscale nicht installiert"}
    except Exception as e:
        info["tailscale"] = {"available": False, "reason": str(e)}

    return info


@router.get("/system/share-base")
def get_share_base(request: Request):
    """Base URL a guest's phone can use to reach this booth (for QR codes).

    The kiosk browser runs on localhost, which is useless in a QR code — so we
    return the box's LAN IP (or a configured override) plus the server port.

    Also advertises the remote gallery when it is enabled with a public URL, so
    the booth can point download links at the off-box (internet-reachable)
    gallery instead of the LAN-only box — useful when guest phones aren't on the
    booth's network.
    """
    cfg = request.app.state.config
    override = get_nested(cfg, "share.base_url", "") or ""
    tunnel = _tunnel_base_url(cfg)
    if override:
        base_url = override.rstrip("/")
    elif tunnel:
        base_url = tunnel
    else:
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
        base_url = f"http://{ip}:{port}"

    return {"base_url": base_url, "remote_gallery": _remote_gallery_share(cfg)}


def _tunnel_base_url(cfg: dict) -> str | None:
    """Public URL of the Cloudflare quick tunnel, when enabled and running.

    The tunnel wrapper (scripts/cloudflared-quick.sh) writes the assigned
    ``*.trycloudflare.com`` URL to ``data/tunnel_url.txt``; we read it here so
    guest QR codes point at the internet-reachable tunnel instead of the LAN IP.
    """
    if not get_nested(cfg, "share.tunnel.enabled", False):
        return None
    from app.config import _BASE_DIR

    try:
        url = (_BASE_DIR / "data" / "tunnel_url.txt").read_text(encoding="utf-8").strip()
    except Exception:
        return None
    return url.rstrip("/") if url.startswith("http") else None


def _remote_gallery_share(cfg: dict) -> dict | None:
    """Public download info for the remote gallery, or None when unavailable.

    A photo uploaded by the sync service lives at ``<public_url>/img/<basename>``
    (see app.services.remote_gallery.REMOTE_IMG_DIR), so the booth can build a
    per-photo link from ``image_base`` + the photo's filename.
    """
    from app.services.remote_gallery import REMOTE_IMG_DIR

    rg = get_nested(cfg, "remote_gallery", {}) or {}
    public_url = (rg.get("public_url") or "").rstrip("/")
    if not rg.get("enabled") or not public_url:
        return None
    return {
        "active": True,
        "gallery_url": public_url,
        "image_base": f"{public_url}/{REMOTE_IMG_DIR}",
    }


# ── Cloudflare quick tunnel (public QR links, no account) ──────────────────

_TUNNEL_SERVICE = "mkphotobox-tunnel.service"


def _tunnel_status(cfg: dict) -> dict:
    import shutil

    from app.config import _BASE_DIR

    url = ""
    try:
        url = (_BASE_DIR / "data" / "tunnel_url.txt").read_text(encoding="utf-8").strip()
    except Exception:
        url = ""
    active = False
    try:
        r = subprocess.run(["systemctl", "is-active", _TUNNEL_SERVICE],
                           capture_output=True, text=True, timeout=5)
        active = r.stdout.strip() == "active"
    except Exception:
        pass
    return {
        "enabled": bool(get_nested(cfg, "share.tunnel.enabled", False)),
        "installed": shutil.which("cloudflared") is not None,
        "service_active": active,
        "url": url if url.startswith("http") else "",
    }


@router.get("/system/tunnel")
def get_tunnel(request: Request, _user=Depends(require_role("admin", "organizer"))):
    """Cloudflare quick-tunnel status: enabled flag, install state, live URL."""
    return _tunnel_status(request.app.state.config)


@router.post("/system/tunnel")
def set_tunnel(body: dict, request: Request,
               session: Session = Depends(get_session),
               user: User = Depends(require_role("admin"))):
    """Enable/disable the Cloudflare quick tunnel: persist the flag and
    start/stop the systemd service. Returns the refreshed status."""
    import json

    from app.config import get_config, set_nested
    from app.models import Setting

    enabled = bool(body.get("enabled"))

    # Persist as a DB Setting (survives restart via apply_db_settings) + in-memory.
    key = "share.tunnel.enabled"
    row = session.exec(select(Setting).where(Setting.key == key)).first()
    if row:
        row.value_json = json.dumps(enabled)
        row.updated_at = time_now()
        row.updated_by = user.id
    else:
        row = Setting(key=key, value_json=json.dumps(enabled), updated_by=user.id)
    session.add(row)
    session.commit()
    cfg = get_config()
    set_nested(cfg, key, enabled)
    request.app.state.config = cfg

    action = "start" if enabled else "stop"
    error = None
    try:
        r = subprocess.run(["sudo", "-n", "systemctl", action, _TUNNEL_SERVICE],
                           capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            error = (r.stderr or r.stdout or f"exit {r.returncode}").strip()[:300]
    except Exception as e:
        error = str(e)

    status = _tunnel_status(cfg)
    status["error"] = error
    return status


def time_now():
    from datetime import datetime
    return datetime.utcnow()


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
    """Restart the service. Prefer ``systemctl restart`` — it runs the app's
    lifespan shutdown first, which releases the camera (gphoto2 exit). A raw
    os.execv would skip that and leave a wedged PTP session → black live stream
    on the fresh process. os.execv is only a fallback when sudo isn't allowed."""
    import subprocess
    import threading

    def _do_restart():
        time.sleep(0.5)
        if _can_sudo(SYSTEMCTL, "restart", SERVICE_NAME):
            subprocess.run(["sudo", "-n", SYSTEMCTL, "restart", SERVICE_NAME], capture_output=True)
            return
        os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=_do_restart, daemon=True).start()
    return {"status": "restarting"}


@router.get("/display/config")
def get_display_config():
    """Return public display settings (no auth required)."""
    cfg = get_config()
    return {
        "preview_size": get_nested(cfg, "display.preview_size", "medium"),
        "idle_live_preview": get_nested(cfg, "display.idle_live_preview", True),
        # Browser-Kamera: die Vorschau spiegelt der Booth selbst per CSS und
        # rechnet sie beim Auslösen wieder heraus (Server-Kameras erledigen das
        # schon im Frame). Siehe app/services/image_transform.py.
        "mirror_preview": get_nested(cfg, "cameras.transform.mirror_preview", True),
        "countdown_seconds": get_nested(cfg, "session.countdown_seconds", 3),
        "capture_lead_ms": get_nested(cfg, "session.capture_lead_ms", 0),
        "gallery_enabled": get_nested(cfg, "gallery.enabled", True),
        "gallery_delete_mode": get_nested(cfg, "gallery.delete_mode", "off"),
        "gallery_delete_recent_minutes": get_nested(cfg, "gallery.delete_recent_minutes", 5),
        # Aspect of a single photo's print output — the booth frames the live
        # preview + crop guide to this so what you see matches what prints.
        "output_aspect": _output_aspect(cfg),
        # Show the booth help button only when Telegram help is actually active.
        "help_button": _help_button_enabled(),
    }


def _help_button_enabled() -> bool:
    from app.services.telegram_service import get_telegram
    svc = get_telegram()
    return bool(svc.ready and svc.notify_help_enabled)


def _output_aspect(cfg: dict) -> dict | None:
    """Aspect {w,h} of the configured print paper (respecting orientation), or
    None when no printer/paper is configured. Used to frame the single-photo
    live preview so it matches the actual print (e.g. 10x15 = 3:2)."""
    from app.services.paper_sizes import paper_size_mm

    pr = get_nested(cfg, "outputs.printer", {}) or {}
    mm = paper_size_mm(pr.get("paper_size") or "")
    if not mm:
        return None
    w, h = mm  # portrait: short × long
    if (pr.get("orientation") or "portrait") == "landscape":
        w, h = h, w
    return {"w": round(w, 1), "h": round(h, 1)}


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
