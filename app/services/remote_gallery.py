"""Remote gallery sync — mirror the whole event to an external web server.

On every new photo the box pushes the image (and its GIF) plus a refreshed
``photos.json`` manifest and the standalone viewer (``index.html``) to a remote
server, so a public, live-updating gallery is hosted off-box. Transport is
pluggable: WebDAV / FTPS / FTP (via curl) or rsync / scp (via ssh).

Design notes:
* Subscribes to ``capture.completed`` and queues photo ids; a single worker
  uploads sequentially with one retry, so a flaky link can't stall captures.
* The manifest is regenerated from the DB (active event) on each push, so it
  always matches what's on the box — late/duplicate events self-heal.
* Disabled until configured; ``test_connection`` uploads a tiny probe file.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

REMOTE_IMG_DIR = "img"          # images live under <remote_dir>/img/
MANIFEST_NAME = "photos.json"
VIEWER_NAME = "index.html"
PROTOCOLS = ("webdav", "ftps", "ftp", "rsync", "scp")


def build_upload_command(protocol: str, opts: dict, local_path: str,
                         remote_rel: str) -> list[str]:
    """Pure (testable) builder: argv to upload *local_path* to *remote_rel*
    (relative to the configured remote dir). Raises ValueError on bad protocol."""
    host = opts.get("host", "")
    port = str(opts.get("port") or "")
    user = opts.get("username", "")
    password = opts.get("password", "")
    remote_dir = (opts.get("remote_dir", "") or "").strip("/")
    key_path = opts.get("key_path", "")
    rel = remote_rel.lstrip("/")

    if protocol in ("ftp", "ftps", "webdav"):
        if protocol == "webdav":
            base = opts.get("url", "").rstrip("/")
            url = f"{base}/{rel}"
        else:
            p = port or "21"
            url = f"ftp://{host}:{p}/{remote_dir}/{rel}" if remote_dir else f"ftp://{host}:{p}/{rel}"
        cmd = ["curl", "-sS", "--fail", "--connect-timeout", "15", "--max-time", "120"]
        if protocol == "ftps":
            cmd += ["--ssl-reqd"]
        if protocol in ("ftp", "ftps"):
            cmd += ["--ftp-create-dirs"]
        if user:
            cmd += ["-u", f"{user}:{password}"]
        cmd += ["-T", local_path, url]
        return cmd

    if protocol in ("rsync", "scp"):
        if not host or not user:
            raise ValueError("rsync/scp benötigen Host und Benutzer")
        target_path = f"{remote_dir}/{rel}" if remote_dir else rel
        ssh_parts = ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]
        if port:
            ssh_parts += ["-p", port] if protocol == "scp" else []
        if key_path:
            ssh_parts += ["-i", key_path]
        if protocol == "rsync":
            ssh = ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]
            if port:
                ssh += ["-p", port]
            if key_path:
                ssh += ["-i", key_path]
            cmd = ["rsync", "-q", "--mkpath", "--timeout=120",
                   "-e", " ".join(ssh), local_path, f"{user}@{host}:{target_path}"]
        else:  # scp — parent dir must exist; caller ensures via _ensure_remote_dir
            cmd = ["scp", "-q", "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]
            if port:
                cmd += ["-P", port]
            if key_path:
                cmd += ["-i", key_path]
            cmd += [local_path, f"{user}@{host}:{target_path}"]
        # password via sshpass when no key is configured
        if not key_path and password:
            cmd = ["sshpass", "-p", password] + cmd
        return cmd

    raise ValueError(f"Unbekanntes Protokoll: {protocol}")


class RemoteGallerySync:
    def __init__(self) -> None:
        self._opts: dict[str, Any] = {}
        self._enabled = False
        self._queue: "asyncio.Queue[int]" = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._bus = None
        self._viewer_pushed = False
        self._state: dict[str, Any] = {
            "enabled": False, "protocol": "", "uploaded": 0, "queued": 0,
            "last_ok": None, "last_error": None, "public_url": "",
        }

    # ── lifecycle ──────────────────────────────────────────────────────────
    def configure(self, cfg: dict) -> None:
        rg = (cfg or {}).get("remote_gallery", {}) or {}
        self._opts = rg
        self._enabled = bool(rg.get("enabled"))
        self._state["enabled"] = self._enabled
        self._state["protocol"] = rg.get("protocol", "")
        self._state["public_url"] = rg.get("public_url", "")

    async def start(self, bus) -> None:
        self._bus = bus
        if bus is not None:
            bus.on("capture.completed", self._on_capture)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _on_capture(self, event: str, data: dict) -> None:
        if not self._enabled:
            return
        # Set-source shots are intermediate — only the finished collage (or a
        # single photo) is mirrored to the remote gallery, not the raw frames.
        if data.get("intermediate"):
            return
        pid = data.get("photo_id")
        if pid is not None:
            await self._queue.put(int(pid))
            self._state["queued"] = self._queue.qsize()

    # ── worker ─────────────────────────────────────────────────────────────
    async def _worker(self) -> None:
        while True:
            pid = await self._queue.get()
            self._state["queued"] = self._queue.qsize()
            if not self._enabled:
                continue
            try:
                ok = await asyncio.to_thread(self._sync_photo, pid)
                if not ok:
                    await asyncio.sleep(2)
                    await asyncio.to_thread(self._sync_photo, pid)  # one retry
            except Exception as e:
                logger.exception("remote_gallery: sync failed for photo %s", pid)
                self._state["last_error"] = str(e)

    # ── sync one photo + manifest + viewer ─────────────────────────────────
    def _sync_photo(self, photo_id: int) -> bool:
        from app.config import get_config
        from app.database import get_engine
        from app.models import Photo
        from sqlmodel import Session

        cfg = get_config()
        storage = Path(cfg["photos"]["storage_path"])
        with Session(get_engine()) as session:
            photo = session.get(Photo, photo_id)
            if photo is None:
                return True  # nothing to do

        files = [photo.filename]
        if photo.gif_filename:
            files.append(photo.gif_filename)
        if photo.thumbnail:
            files.append(photo.thumbnail)   # small tile image for a fast-loading grid

        for fname in files:
            local = storage / fname
            if not local.exists():
                continue
            self._ensure_remote_dir(f"{REMOTE_IMG_DIR}")
            self._upload(str(local), f"{REMOTE_IMG_DIR}/{Path(fname).name}")

        self._push_manifest()
        if not self._viewer_pushed:
            self._push_viewer()
            self._viewer_pushed = True

        self._state["uploaded"] = self._state.get("uploaded", 0) + 1
        from datetime import datetime
        self._state["last_ok"] = datetime.utcnow().isoformat()
        self._state["last_error"] = None
        return True

    def _build_manifest(self) -> dict:
        import json as _json

        from app.database import get_engine
        from app.models import Event, Photo, PhotoSession
        from sqlmodel import Session, select

        with Session(get_engine()) as session:
            event = session.exec(select(Event).where(Event.is_active == True)).first()
            if event is None:
                return {"event": None, "photos": []}
            rows = session.exec(
                select(Photo).join(PhotoSession)
                .where(PhotoSession.event_id == event.id)
                .order_by(Photo.captured_at.desc()).limit(1000)
            ).all()
            # Raw set shots (sources of a collage) shouldn't appear as separate
            # images — only the finished collage. Collect their ids and drop them.
            source_ids: set[int] = set()
            for p in rows:
                try:
                    meta = _json.loads(p.metadata_json or "{}")
                except (ValueError, TypeError):
                    continue
                if meta.get("collage"):
                    source_ids.update(int(i) for i in (meta.get("source_photo_ids") or []))
            photos = [p for p in rows if p.id not in source_ids]
            return {
                "event": event.name,
                "photos": [
                    {"url": f"{REMOTE_IMG_DIR}/{Path(p.filename).name}",
                     "thumb": f"{REMOTE_IMG_DIR}/{Path(p.thumbnail).name}" if p.thumbnail else None,
                     "gif": f"{REMOTE_IMG_DIR}/{Path(p.gif_filename).name}" if p.gif_filename else None,
                     "name": p.filename,
                     "ts": p.captured_at.isoformat() if p.captured_at else None}
                    for p in photos
                ],
            }

    def _push_manifest(self) -> None:
        data = json.dumps(self._build_manifest(), ensure_ascii=False)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(data)
            tmp = f.name
        try:
            self._upload(tmp, MANIFEST_NAME)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def _push_viewer(self) -> None:
        from app.services.viewer_assets import live_viewer_html
        title = self._opts.get("title") or "Foto-Galerie"
        html = live_viewer_html(MANIFEST_NAME, title)
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
            f.write(html)
            tmp = f.name
        try:
            self._upload(tmp, VIEWER_NAME)
        finally:
            Path(tmp).unlink(missing_ok=True)

    # ── transport ──────────────────────────────────────────────────────────
    def _ensure_remote_dir(self, rel: str) -> None:
        """Best-effort remote mkdir (only needed for webdav/scp; ftp/rsync auto-create)."""
        protocol = self._opts.get("protocol", "")
        try:
            if protocol == "webdav":
                base = self._opts.get("url", "").rstrip("/")
                cmd = ["curl", "-sS", "--connect-timeout", "15", "-X", "MKCOL", f"{base}/{rel.strip('/')}/"]
                if self._opts.get("username"):
                    cmd[2:2] = ["-u", f"{self._opts['username']}:{self._opts.get('password','')}"]
                subprocess.run(cmd, capture_output=True, timeout=30)
            elif protocol == "scp":
                self._ssh_mkdir(rel)
        except Exception:
            pass

    def _ssh_mkdir(self, rel: str) -> None:
        o = self._opts
        remote_dir = (o.get("remote_dir", "") or "").strip("/")
        target = f"{remote_dir}/{rel}".strip("/")
        ssh = ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]
        if o.get("port"):
            ssh += ["-p", str(o["port"])]
        if o.get("key_path"):
            ssh += ["-i", o["key_path"]]
        ssh += [f"{o['username']}@{o['host']}", f"mkdir -p '{target}'"]
        if not o.get("key_path") and o.get("password"):
            ssh = ["sshpass", "-p", o["password"]] + ssh
        subprocess.run(ssh, capture_output=True, timeout=30)

    def _upload(self, local_path: str, remote_rel: str) -> None:
        cmd = build_upload_command(self._opts.get("protocol", ""), self._opts, local_path, remote_rel)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            msg = (r.stderr or r.stdout or f"exit {r.returncode}").strip()[:300]
            self._state["last_error"] = msg
            raise RuntimeError(f"Upload {remote_rel} fehlgeschlagen: {msg}")

    # ── public helpers ─────────────────────────────────────────────────────
    @property
    def state(self) -> dict:
        return dict(self._state)

    def test_connection(self) -> dict:
        """Upload a tiny probe file to validate credentials/path."""
        if self._opts.get("protocol") not in PROTOCOLS:
            return {"ok": False, "message": "Kein gültiges Protokoll gewählt."}
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("mkphotobox remote-gallery test\n")
            tmp = f.name
        try:
            self._ensure_remote_dir(REMOTE_IMG_DIR)
            self._upload(tmp, ".mkphotobox-test.txt")
            return {"ok": True, "message": "Verbindung ok — Testdatei hochgeladen."}
        except Exception as e:
            return {"ok": False, "message": str(e)}
        finally:
            Path(tmp).unlink(missing_ok=True)

    async def resync_all(self) -> dict:
        """Queue every photo of the active event for re-upload."""
        from app.database import get_engine
        from app.models import Event, Photo, PhotoSession
        from sqlmodel import Session, select

        if not self._enabled:
            return {"status": "error", "message": "Remote-Galerie ist deaktiviert."}
        self._viewer_pushed = False
        with Session(get_engine()) as session:
            event = session.exec(select(Event).where(Event.is_active == True)).first()
            if event is None:
                return {"status": "error", "message": "Kein aktives Event."}
            ids = session.exec(
                select(Photo.id).join(PhotoSession)
                .where(PhotoSession.event_id == event.id)
                .order_by(Photo.captured_at)
            ).all()
        for pid in ids:
            await self._queue.put(int(pid))
        self._state["queued"] = self._queue.qsize()
        return {"status": "ok", "queued": len(ids)}


_service: Optional[RemoteGallerySync] = None


def get_remote_gallery() -> RemoteGallerySync:
    global _service
    if _service is None:
        _service = RemoteGallerySync()
    return _service
