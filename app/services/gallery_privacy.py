"""Galerie-Sichtschutz — ältere „Runden“ werden weichgezeichnet.

Auf größeren Feiern steht die Box stundenlang offen herum. Wer gerade
fotografiert, will seine Bilder in der Galerie wiederfinden; die Fotos der
Gruppen davor gehen ihn aber nichts an. Deshalb teilt dieses Modul die Fotos
eines Events in Runden ein und zeichnet alles außer der laufenden Runde weich.

Runde: Fotos, zwischen denen nie mehr als ``gallery.privacy_idle_minutes``
Pause liegt. Das lässt sich allein aus ``Photo.captured_at`` ableiten — keine
Spalte, keine Migration, und es stimmt auch für Fotos von vor dem Update.

Wann wird die letzte Runde unscharf? Sobald seit ihrem letzten Foto mehr als
die Leerlaufzeit vergangen ist. Sonst sähe die nächste Gruppe, die nach einer
Viertelstunde an die Box tritt, beim Öffnen der Galerie noch alles von der
vorherigen. Grenzfall „genau N Minuten“ zählt noch zur Runde (Pause ≤ N), an
beiden Stellen gleich, damit Rundenbildung und Ablauf nicht auseinanderlaufen.

Das ist Sichtschutz, keine Zugriffskontrolle: Die Datei-Links (/file, /gif,
online img/<name>) funktionieren weiter, damit gespeicherte Download- und
QR-Links der Gäste nicht kaputtgehen. Ausgeblendet wird nur, was die Galerie
von sich aus zeigt.

Die weichgezeichnete Fassung wird auf dem Server gerendert (CSS-Blur ließe
sich mit einem Rechtsklick abschalten) und unter ``<storage>/blur/`` gecacht.
Der ``PrivacyWatcher`` erzeugt sie im Hintergrund, sobald eine Runde abläuft,
und stößt die Online-Galerie an — dort ändert sich sonst nichts, bis das
nächste Foto kommt.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

BLUR_DIR = "blur"
DEFAULT_IDLE_MINUTES = 10
#: Kantenlänge der weichgezeichneten Fassung. Mehr braucht eine Kachel nicht,
#: und ein kleines Bild verrät auch nach dem Hochskalieren keine Gesichter.
BLUR_SIZE = 360


# ── Einstellungen ──────────────────────────────────────────────────────────

def is_enabled(cfg: dict | None) -> bool:
    return bool(((cfg or {}).get("gallery", {}) or {}).get("privacy_blur", False))


def idle_minutes(cfg: dict | None) -> float:
    raw = ((cfg or {}).get("gallery", {}) or {}).get("privacy_idle_minutes", DEFAULT_IDLE_MINUTES)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_IDLE_MINUTES
    # Unter einer Minute wäre die eigene Runde schon beim Blättern weg, über
    # einen Tag ist der Schutz praktisch aus.
    return max(1.0, min(24 * 60.0, value))


# ── Rundenbildung (rein, testbar) ─────────────────────────────────────────

def sharp_cutoff(timestamps: Iterable[Optional[datetime]], idle: timedelta,
                 now: datetime) -> Optional[datetime]:
    """Beginn der laufenden Runde — Fotos ab diesem Zeitpunkt bleiben scharf.

    ``None`` heißt: es läuft keine Runde (keine Fotos, oder seit dem letzten
    mehr als *idle* Leerlauf), also ist alles unscharf. Eine Pause von genau
    *idle* trennt noch keine Runde."""
    ts = sorted(t for t in timestamps if t is not None)
    if not ts or now - ts[-1] > idle:
        return None
    start = ts[-1]
    for earlier in reversed(ts[:-1]):
        if start - earlier > idle:
            break
        start = earlier
    return start


def round_expires_at(timestamps: Iterable[Optional[datetime]], idle: timedelta) -> Optional[datetime]:
    """Wann die laufende Runde ohne neues Foto unscharf wird."""
    ts = [t for t in timestamps if t is not None]
    return max(ts) + idle if ts else None


def is_blurred(captured_at: Optional[datetime], cutoff: Optional[datetime]) -> bool:
    if cutoff is None:
        return True
    return captured_at is None or captured_at < cutoff


# ── Datenbank ──────────────────────────────────────────────────────────────

def event_timestamps(session, event_id: int) -> list[datetime]:
    from sqlmodel import select

    from app.models import Photo, PhotoSession
    return [t for t in session.exec(
        select(Photo.captured_at).join(PhotoSession).where(PhotoSession.event_id == event_id)
    ).all() if t is not None]


def cutoff_for_event(session, event_id: int, cfg: dict,
                     now: Optional[datetime] = None) -> Optional[datetime]:
    """Wie ``sharp_cutoff`` für ein Event aus der DB. Nur aufrufen, wenn der
    Sichtschutz an ist — sonst ist ohnehin alles scharf."""
    idle = timedelta(minutes=idle_minutes(cfg))
    return sharp_cutoff(event_timestamps(session, event_id), idle, now or datetime.utcnow())


def blurred_ids_for_event(session, event_id: int, cfg: dict,
                          now: Optional[datetime] = None) -> set[int]:
    """IDs aller Fotos des Events, die die Galerie gerade unscharf zeigen soll
    (leer, wenn der Sichtschutz aus ist)."""
    if not is_enabled(cfg):
        return set()
    from sqlmodel import select

    from app.models import Photo, PhotoSession
    rows = session.exec(
        select(Photo.id, Photo.captured_at).join(PhotoSession)
        .where(PhotoSession.event_id == event_id)
    ).all()
    idle = timedelta(minutes=idle_minutes(cfg))
    cutoff = sharp_cutoff((t for _, t in rows), idle, now or datetime.utcnow())
    return {pid for pid, t in rows if is_blurred(t, cutoff)}


def photo_is_blurred(session, photo, cfg: dict, now: Optional[datetime] = None) -> bool:
    """Für Einzelabrufe (/thumb): gehört *photo* zu einer abgelaufenen Runde?"""
    if not is_enabled(cfg):
        return False
    from app.models import PhotoSession
    ps = session.get(PhotoSession, photo.session_id)
    if ps is None:
        return True
    return is_blurred(photo.captured_at, cutoff_for_event(session, ps.event_id, cfg, now))


# ── Weichgezeichnete Fassung ──────────────────────────────────────────────

def blur_name(photo) -> str:
    """Dateiname der unscharfen Fassung. Bewusst nicht aus dem Fotonamen
    abgeleitet: online liegt sie neben dem Original in img/, und
    „<name>_blur.jpg“ verriete sofort, wie das Original heißt."""
    digest = hashlib.sha256(f"{photo.id}:{photo.filename}".encode()).hexdigest()[:16]
    return f"b_{digest}.jpg"


def blur_path(storage: Path, photo) -> Path:
    return Path(storage) / BLUR_DIR / blur_name(photo)


def _source(storage: Path, photo) -> Optional[Path]:
    # Das Vorschaubild reicht als Quelle und ist viel schneller geöffnet als
    # ein 24-Megapixel-JPEG.
    for rel in (photo.thumbnail, photo.filename):
        if rel and (Path(storage) / rel).exists():
            return Path(storage) / rel
    return None


def is_fresh(storage: Path, photo) -> bool:
    """Gibt es eine unscharfe Fassung, die nicht älter ist als ihre Quelle?
    Das Gästebuch überschreibt Foto und Vorschaubild — dann ist sie veraltet,
    auch wenn das explizite ``invalidate`` einmal nicht gegriffen hat."""
    out = blur_path(storage, photo)
    src = _source(storage, photo)
    if not out.exists() or src is None:
        return False
    try:
        return out.stat().st_mtime >= src.stat().st_mtime
    except OSError:
        return False


def render_blur(src: Path, out: Path, size: int = BLUR_SIZE) -> Path:
    """Kleine, stark weichgezeichnete Kopie schreiben (ohne EXIF — darin
    stünden Event, Kamera und Ort). Atomar über eine Temp-Datei, damit ein
    gleichzeitiger Abruf nie eine halbe Datei bekommt."""
    from PIL import Image, ImageFilter, ImageOps

    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((size, size))
        # Erst auf wenige Pixel verkleinern, dann zurück und weichzeichnen:
        # Das zerstört Gesichter gründlich, der Gaußfilter allein ließe bei
        # großem Kontrast Umrisse stehen. Farben und Stimmung bleiben erkennbar.
        w, h = im.size
        tiny = im.resize((max(1, w // 24), max(1, h // 24)), Image.BILINEAR)
        im = tiny.resize((w, h), Image.BICUBIC).filter(
            ImageFilter.GaussianBlur(radius=max(4, max(w, h) // 40)))
        tmp = out.with_suffix(".tmp")
        im.save(tmp, "JPEG", quality=70)
    tmp.replace(out)
    return out


def ensure_blur(storage: Path, photo) -> Optional[Path]:
    """Unscharfe Fassung liefern, bei Bedarf erzeugen. Blockiert — aus
    Request-Handlern nur über den Threadpool (sync-Endpunkt / to_thread)."""
    if is_fresh(storage, photo):
        return blur_path(storage, photo)
    src = _source(storage, photo)
    if src is None:
        return None
    try:
        return render_blur(src, blur_path(storage, photo))
    except Exception:
        logger.exception("Unscharfe Fassung für Foto %s fehlgeschlagen", photo.id)
        return None


def invalidate(storage: Path, photo) -> None:
    """Nach dem Bearbeiten (Gästebuch) oder Löschen eines Fotos."""
    try:
        blur_path(storage, photo).unlink(missing_ok=True)
    except OSError:
        pass


# ── Hintergrund: Runden ablaufen lassen ───────────────────────────────────

class PrivacyWatcher:
    """Prüft regelmäßig, ob eine Runde abgelaufen ist.

    Lokal entscheiden die Galerie-Endpunkte bei jedem Abruf selbst; hier
    werden nur die unscharfen Fassungen vorab erzeugt, damit der erste Abruf
    nach Rundenende nicht auf Pillow wartet. Die Online-Galerie dagegen ist
    eine statische photos.json — die muss jemand neu hochladen, sobald sich
    ändert, welche Fotos unscharf sind."""

    INTERVAL = 30.0   # Sekunden; so lange darf die Online-Galerie nachhinken

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._last_signature: Optional[tuple] = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Galerie-Sichtschutz: Prüfung fehlgeschlagen")
            await asyncio.sleep(self.INTERVAL)

    async def tick(self) -> None:
        signature, todo = await asyncio.to_thread(self._scan)
        if todo:
            await asyncio.to_thread(self._render_all, todo)
        # Auch beim ersten Durchlauf nach dem Start, wenn der Schutz an ist: Lief
        # die Runde ab, während die Box aus war, steht online noch alles scharf.
        first = self._last_signature is None
        if signature != self._last_signature and (not first or signature[0]):
            from app.services.remote_gallery import get_remote_gallery
            await get_remote_gallery().request_manifest_refresh()
        self._last_signature = signature

    @staticmethod
    def _scan():
        """(Signatur des Zustands, Fotos ohne frische unscharfe Fassung)."""
        from sqlmodel import Session, select

        from app.config import get_config
        from app.database import get_engine
        from app.models import Event, Photo, PhotoSession

        cfg = get_config()
        enabled = is_enabled(cfg)
        storage = Path(cfg["photos"]["storage_path"])
        with Session(get_engine()) as session:
            event = session.exec(select(Event).where(Event.is_active == True)).first()  # noqa: E712
            if event is None or not enabled:
                return (enabled, None, frozenset()), []
            photos = session.exec(
                select(Photo).join(PhotoSession).where(PhotoSession.event_id == event.id)
            ).all()
            idle = timedelta(minutes=idle_minutes(cfg))
            cutoff = sharp_cutoff((p.captured_at for p in photos), idle, datetime.utcnow())
            blurred = [p for p in photos if is_blurred(p.captured_at, cutoff)]
            todo = [p for p in blurred if not is_fresh(storage, p)]
            for p in todo:
                session.expunge(p)   # wird nach dem Schließen der Session noch gelesen
        return (enabled, event.id, frozenset(p.id for p in blurred)), todo

    @staticmethod
    def _render_all(photos) -> None:
        from app.config import get_config
        storage = Path(get_config()["photos"]["storage_path"])
        for photo in photos:
            ensure_blur(storage, photo)


_watcher: Optional[PrivacyWatcher] = None


def get_watcher() -> PrivacyWatcher:
    global _watcher
    if _watcher is None:
        _watcher = PrivacyWatcher()
    return _watcher
