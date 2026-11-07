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
            bus.on("photo.gif_ready", self._on_gif_ready)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._worker())
        if self._enabled:
            asyncio.create_task(self._catch_up())

    # ── Nachholen nach einem Neustart ──────────────────────────────────────
    # Die Warteschlange liegt nur im Speicher. Ein Neustart (Software-Update,
    # Stromausfall) mitten im Upload verlor also das Foto: es kam nie in der
    # Online-Galerie an. Deshalb steht auf der Platte, welche Fotos oben sind,
    # und beim Start wird nachgeholt, was fehlt.
    def _synced_path(self) -> Path:
        from app.config import get_config
        return Path(get_config()["photos"]["storage_path"]) / ".remote_synced.json"

    def _load_synced(self) -> set[int]:
        try:
            return {int(i) for i in json.loads(self._synced_path().read_text(encoding="utf-8"))}
        except (OSError, ValueError, TypeError):
            return set()

    def _mark_synced(self, photo_id: int) -> None:
        done = self._load_synced()
        done.add(int(photo_id))
        path = self._synced_path()
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(sorted(done)), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            logger.debug("remote_gallery: Vermerk nicht schreibbar", exc_info=True)

    def _pending_ids(self) -> list[int]:
        """Fotos der Online-Galerie (wie im Manifest: ohne Set-Rohbilder), die
        noch nicht als hochgeladen vermerkt sind — älteste zuerst."""
        from app.database import get_engine
        from app.models import Event, Photo, PhotoSession
        from sqlmodel import Session, select

        with Session(get_engine()) as session:
            event = session.exec(select(Event).where(Event.is_active == True)).first()
            if event is None:
                return []
            rows = session.exec(
                select(Photo).join(PhotoSession).where(PhotoSession.event_id == event.id)
                .order_by(Photo.captured_at.desc()).limit(1000)
            ).all()
            source_ids: set[int] = set()
            for p in rows:
                try:
                    meta = json.loads(p.metadata_json or "{}")
                except (ValueError, TypeError):
                    continue
                if meta.get("collage"):
                    source_ids.update(int(i) for i in (meta.get("source_photo_ids") or []))
            done = self._load_synced()
            return [p.id for p in reversed(rows) if p.id not in source_ids and p.id not in done]

    async def _catch_up(self) -> None:
        await asyncio.sleep(10)   # erst den Start fertig werden lassen
        try:
            pending = await asyncio.to_thread(self._pending_ids)
        except Exception:
            logger.exception("remote_gallery: Nachholen fehlgeschlagen")
            return
        if pending:
            logger.info("remote_gallery: %d Foto(s) nachholen", len(pending))
        for pid in pending:
            # Diff-Modus: was schon gleich groß oben liegt, wird übersprungen
            await self._queue.put((pid, True))
        self._state["queued"] = self._queue.qsize()

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
            await self._queue.put((int(pid), False))   # new photo → always upload
            self._state["queued"] = self._queue.qsize()

    async def _on_gif_ready(self, event: str, data: dict) -> None:
        """Das GIF entsteht im Hintergrund — meist erst nach dem Upload des
        Fotos, der direkt auf capture.completed folgt. Ohne das hier fehlte es
        online. Diff-Modus: das Foto selbst liegt schon oben und wird
        übersprungen, nur das GIF (und das Manifest) kommen nach."""
        if not self._enabled:
            return
        pid = data.get("photo_id")
        if pid is not None:
            await self._queue.put((int(pid), True))
            self._state["queued"] = self._queue.qsize()

    async def request_manifest_refresh(self) -> None:
        """photos.json neu hochladen, ohne dass ein Foto dazukam."""
        if self._enabled:
            await self._queue.put((None, False))
            self._state["queued"] = self._queue.qsize()

    # ── worker ─────────────────────────────────────────────────────────────
    async def _worker(self) -> None:
        while True:
            item = await self._queue.get()
            pid, skip_existing = item if isinstance(item, tuple) else (item, False)
            self._state["queued"] = self._queue.qsize()
            if not self._enabled:
                continue
            if pid is None:
                # Nur das Manifest (Galerie-Sichtschutz: eine Runde ist ohne
                # neues Foto abgelaufen). Über dieselbe Schlange, damit nie zwei
                # Uploads gleichzeitig laufen.
                try:
                    await asyncio.to_thread(self._push_manifest)
                except Exception as e:
                    logger.exception("remote_gallery: manifest refresh failed")
                    self._state["last_error"] = str(e)
                continue
            try:
                ok = await asyncio.to_thread(self._sync_photo, pid, skip_existing)
                if not ok:
                    await asyncio.sleep(2)
                    await asyncio.to_thread(self._sync_photo, pid, skip_existing)  # one retry
            except Exception as e:
                logger.exception("remote_gallery: sync failed for photo %s", pid)
                self._state["last_error"] = str(e)

    # ── sync one photo + manifest + viewer ─────────────────────────────────
    def _sync_photo(self, photo_id: int, skip_existing: bool = False) -> bool:
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
            rel = f"{REMOTE_IMG_DIR}/{Path(fname).name}"
            # Diff mode (re-upload button): skip files already on the server with
            # the same size, so we don't re-push everything / waste bandwidth.
            if skip_existing and self._remote_size(rel) == local.stat().st_size:
                self._state["skipped"] = self._state.get("skipped", 0) + 1
                continue
            self._ensure_remote_dir(f"{REMOTE_IMG_DIR}")
            self._upload(str(local), rel)

        self._push_manifest()
        if not self._viewer_pushed:
            self._push_viewer()
            self._viewer_pushed = True

        self._mark_synced(photo_id)
        self._state["uploaded"] = self._state.get("uploaded", 0) + 1
        from datetime import datetime
        self._state["last_ok"] = datetime.utcnow().isoformat()
        self._state["last_error"] = None
        return True

    def _build_manifest(self) -> dict:
        return self._build_manifest_and_blurred()[0]

    def _build_manifest_and_blurred(self) -> tuple[dict, list]:
        """Manifest plus die Fotos, die darin nur unscharf vorkommen (deren
        weichgezeichnete Kopie muss vor dem Manifest oben liegen)."""
        import json as _json
        from datetime import datetime, timedelta

        from app.config import get_config
        from app.services import gallery_privacy

        from app.database import get_engine
        from app.models import Event, Photo, PhotoSession
        from sqlmodel import Session, select

        with Session(get_engine()) as session:
            event = session.exec(select(Event).where(Event.is_active == True)).first()
            if event is None:
                return {"event": None, "photos": []}, []
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

            # Sichtschutz: Runden rechnen über ALLE Fotos (auch die Rohbilder
            # eines Sets), sonst risse eine lange Collage-Session die Runde auf.
            cfg = get_config()
            cutoff = None
            if gallery_privacy.is_enabled(cfg):
                idle = timedelta(minutes=gallery_privacy.idle_minutes(cfg))
                cutoff = gallery_privacy.sharp_cutoff(
                    (p.captured_at for p in rows), idle, datetime.utcnow())
            blurred = [p for p in photos if gallery_privacy.is_enabled(cfg)
                       and gallery_privacy.is_blurred(p.captured_at, cutoff)]
            blurred_ids = {p.id for p in blurred}
            for p in blurred:
                session.expunge(p)

            def entry(p) -> dict:
                ts = p.captured_at.isoformat() if p.captured_at else None
                if p.id in blurred_ids:
                    # Nur die unscharfe Kopie — kein Link aufs Original, kein
                    # Dateiname. Das Original bleibt unter img/<name> liegen,
                    # damit QR- und Download-Links der Gäste weiter gehen.
                    return {"thumb": f"{REMOTE_IMG_DIR}/{gallery_privacy.blur_name(p)}",
                            "blurred": True, "ts": ts}
                return {"url": f"{REMOTE_IMG_DIR}/{Path(p.filename).name}",
                        "thumb": f"{REMOTE_IMG_DIR}/{Path(p.thumbnail).name}" if p.thumbnail else None,
                        "gif": f"{REMOTE_IMG_DIR}/{Path(p.gif_filename).name}" if p.gif_filename else None,
                        "name": p.filename,
                        "ts": ts}

            return {"event": event.name, "photos": [entry(p) for p in photos]}, blurred

    def _push_manifest(self) -> None:
        manifest, blurred = self._build_manifest_and_blurred()
        self._upload_blurred(blurred)
        data = json.dumps(manifest, ensure_ascii=False)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(data)
            tmp = f.name
        try:
            self._upload(tmp, MANIFEST_NAME)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def _upload_blurred(self, photos: list) -> None:
        """Unscharfe Kopien hochladen, die online noch fehlen.

        Welche schon oben liegen, steht in blur/.remote_uploaded.json (Name →
        mtime): Nach einem Neustart sonst jede einzeln erneut hochzuladen, hielte
        die Schlange bei 1000 Fotos minutenlang auf. Eine neu gerenderte Fassung
        (Gästebuch) hat eine neue mtime und geht deshalb wieder hoch."""
        if not photos:
            return
        from app.config import get_config
        from app.services import gallery_privacy

        storage = Path(get_config()["photos"]["storage_path"])
        record_path = storage / gallery_privacy.BLUR_DIR / ".remote_uploaded.json"
        try:
            done = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            done = {}
        changed = False
        try:
            for p in photos:
                local = gallery_privacy.ensure_blur(storage, p)
                if local is None:
                    continue
                mtime = int(local.stat().st_mtime)
                if done.get(local.name) == mtime:
                    continue
                self._ensure_remote_dir(REMOTE_IMG_DIR)
                self._upload(str(local), f"{REMOTE_IMG_DIR}/{local.name}")
                done[local.name] = mtime
                changed = True
        finally:
            if changed:
                record_path.parent.mkdir(parents=True, exist_ok=True)
                record_path.write_text(json.dumps(done), encoding="utf-8")

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

    def _remote_size(self, remote_rel: str) -> Optional[int]:
        """Size (bytes) of a remote file, or None if missing / unknown — used to
        skip already-uploaded files on re-sync. Works for webdav/ftp/ftps via a
        curl HEAD; rsync/scp return None (rsync self-diffs, scp re-uploads)."""
        protocol = self._opts.get("protocol", "")
        rel = remote_rel.lstrip("/")
        if protocol not in ("webdav", "ftp", "ftps"):
            return None
        try:
            if protocol == "webdav":
                url = f"{self._opts.get('url', '').rstrip('/')}/{rel}"
            else:
                p = str(self._opts.get("port") or "") or "21"
                host = self._opts.get("host", "")
                remote_dir = (self._opts.get("remote_dir", "") or "").strip("/")
                url = f"ftp://{host}:{p}/{remote_dir}/{rel}" if remote_dir else f"ftp://{host}:{p}/{rel}"
            cmd = ["curl", "-sS", "-I", "--connect-timeout", "15"]
            if protocol == "ftps":
                cmd += ["--ssl-reqd"]
            if self._opts.get("username"):
                cmd += ["-u", f"{self._opts['username']}:{self._opts.get('password', '')}"]
            cmd.append(url)
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                return None
            status_ok = False
            size = None
            for line in r.stdout.splitlines():
                s = line.strip()
                low = s.lower()
                if low.startswith("http/"):
                    parts = s.split()
                    status_ok = len(parts) > 1 and parts[1].startswith("2")
                elif low.startswith("content-length:"):
                    try:
                        size = int(s.split(":", 1)[1].strip())
                    except ValueError:
                        pass
            if protocol == "webdav" and not status_ok:   # 404 etc. → not there
                return None
            return size
        except Exception:
            return None

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
        """Queue every photo of the active event — but in DIFF mode: files already
        on the server (same size) are skipped instead of blindly overwritten."""
        from app.database import get_engine
        from app.models import Event, Photo, PhotoSession
        from sqlmodel import Session, select

        if not self._enabled:
            return {"status": "error", "message": "Remote-Galerie ist deaktiviert."}
        self._viewer_pushed = False
        self._state["skipped"] = 0
        # Neu synchronisieren heißt auch: unscharfe Kopien nicht für vorhanden halten
        # (der Server könnte geleert worden sein).
        try:
            from app.config import get_config
            from app.services import gallery_privacy
            (Path(get_config()["photos"]["storage_path"]) / gallery_privacy.BLUR_DIR
             / ".remote_uploaded.json").unlink(missing_ok=True)
        except OSError:
            pass
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
            await self._queue.put((int(pid), True))   # True = skip files already there
        self._state["queued"] = self._queue.qsize()
        return {"status": "ok", "queued": len(ids)}


_service: Optional[RemoteGallerySync] = None


def get_remote_gallery() -> RemoteGallerySync:
    global _service
    if _service is None:
        _service = RemoteGallerySync()
    return _service
