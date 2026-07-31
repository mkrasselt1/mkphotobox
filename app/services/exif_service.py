"""Metadata (EXIF) tagging for every image file the box produces.

Every photo, collage and GIF gets stamped with

    * the event details  — name, slug, date, and the location it was shot at
    * the camera info    — make/model of the capture camera, module id
    * the GPS position   — latitude/longitude/altitude configured on the event

JPEGs carry a real EXIF APP1 segment; GIFs (which have no EXIF) get the same
information as a GIF comment block.

Design notes
------------
* Tagging a JPEG **never re-encodes** it — the APP1 segment is spliced into the
  raw byte stream, so a DSLR's full-quality file stays byte-identical apart from
  its metadata.
* EXIF the camera itself wrote (exposure, ISO, lens, its own Make/Model) is kept
  and only *extended*; we never overwrite a value the camera provided.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

SOFTWARE = "MKPhotobox"

# ── EXIF tag ids (0th IFD) ────────────────────────────────────────────────
_IMAGE_DESCRIPTION = 0x010E
_MAKE = 0x010F
_MODEL = 0x0110
_SOFTWARE_TAG = 0x0131
_DATETIME = 0x0132
_ARTIST = 0x013B
_COPYRIGHT = 0x8298
_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825

# Exif sub-IFD
_DATETIME_ORIGINAL = 0x9003
_DATETIME_DIGITIZED = 0x9004
_OFFSET_TIME = 0x9010
_OFFSET_TIME_ORIGINAL = 0x9011
_OFFSET_TIME_DIGITIZED = 0x9012
_USER_COMMENT = 0x9286
_XP_TITLE = 0x9C9B
_XP_COMMENT = 0x9C9C
_XP_SUBJECT = 0x9C9F

# GPS sub-IFD
_GPS_VERSION = 0x0000
_GPS_LAT_REF = 0x0001
_GPS_LAT = 0x0002
_GPS_LON_REF = 0x0003
_GPS_LON = 0x0004
_GPS_ALT_REF = 0x0005
_GPS_ALT = 0x0006
_GPS_TIMESTAMP = 0x0007
_GPS_MAP_DATUM = 0x0012
_GPS_PROCESSING = 0x001B
_GPS_AREA_INFO = 0x001C
_GPS_DATESTAMP = 0x001D

_MAX_APP1 = 65533  # APP1 payload limit (segment length field is 16 bit)


@dataclass(frozen=True)
class FileMeta:
    """Everything that gets stamped into a produced file."""

    event_name: str = ""
    event_slug: str = ""
    event_starts_at: Optional[datetime] = None
    location_name: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    camera_make: str = ""
    camera_model: str = ""
    camera_module: str = ""
    artist: str = ""
    copyright: str = ""
    note: str = ""          # free-form extra ("Collage aus 3 Aufnahmen")
    software: str = SOFTWARE

    @property
    def has_gps(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def description(self) -> str:
        """Human-readable one-liner used for ImageDescription."""
        parts = [self.event_name or SOFTWARE]
        if self.location_name:
            parts.append(self.location_name)
        if self.camera_model:
            parts.append(self.camera_model)
        if self.note:
            parts.append(self.note)
        return " - ".join(p for p in parts if p)

    def long_comment(self) -> str:
        """Verbose key/value dump used for UserComment / GIF comment."""
        rows: list[tuple[str, str]] = [("Veranstaltung", self.event_name)]
        if self.event_slug:
            rows.append(("Kennung", self.event_slug))
        if self.event_starts_at:
            rows.append(("Beginn", self.event_starts_at.strftime("%Y-%m-%d %H:%M")))
        if self.location_name:
            rows.append(("Ort", self.location_name))
        if self.has_gps:
            rows.append(("Koordinaten", f"{self.latitude:.6f}, {self.longitude:.6f}"))
        if self.altitude is not None:
            rows.append(("Höhe", f"{self.altitude:.1f} m"))
        if self.camera_model or self.camera_make:
            # our own name is redundant here — it is already the "Software" row
            make = "" if self.camera_make == SOFTWARE else self.camera_make
            rows.append(("Kamera", " ".join(x for x in (make, self.camera_model) if x)))
        if self.camera_module:
            rows.append(("Kameramodul", self.camera_module))
        if self.note:
            rows.append(("Hinweis", self.note))
        rows.append(("Software", self.software))
        return "; ".join(f"{k}: {v}" for k, v in rows if v)


# ── Building the meta from the running system ────────────────────────────

def meta_for_event(event: Any, cfg: dict | None = None, cameras: Any = None,
                   note: str = "") -> FileMeta:
    """Collect event + camera metadata for a file about to be written.

    ``event`` is an :class:`app.models.Event` (or None), ``cameras`` the
    CameraManager. Both are optional so callers never have to guard.
    """
    exif_cfg = (cfg or {}).get("exif", {}) if isinstance(cfg, dict) else {}
    include_location = exif_cfg.get("include_location", True)

    make, model = _camera_identity(cameras)
    return FileMeta(
        event_name=getattr(event, "name", "") or "",
        event_slug=getattr(event, "slug", "") or "",
        event_starts_at=getattr(event, "starts_at", None),
        location_name=(getattr(event, "location_name", "") or "") if include_location else "",
        latitude=getattr(event, "latitude", None) if include_location else None,
        longitude=getattr(event, "longitude", None) if include_location else None,
        altitude=getattr(event, "altitude", None) if include_location else None,
        camera_make=make,
        camera_model=model,
        camera_module=(getattr(cameras, "capture_id", None) or getattr(cameras, "active_id", "") or ""),
        artist=exif_cfg.get("artist", "") or "",
        copyright=exif_cfg.get("copyright", "") or "",
        note=note,
        software=_software_string(),
    )


def is_enabled(cfg: dict | None) -> bool:
    if not isinstance(cfg, dict):
        return True
    return bool(cfg.get("exif", {}).get("enabled", True))


def _software_string() -> str:
    try:
        from importlib.metadata import version

        return f"{SOFTWARE} {version('mkphotobox')}"
    except Exception:
        return SOFTWARE


# Fallback labels for cameras that cannot report a model of their own.
_CAMERA_LABELS = {
    "opencv": "USB-Kamera (OpenCV)",
    "webrtc": "Browser-Kamera (WebRTC)",
    "gphoto2": "gphoto2",
    "digicamcontrol": "digiCamControl",
}


def _camera_identity(cameras: Any) -> tuple[str, str]:
    """Best-effort make/model of the camera that takes the picture.

    A DSLR reports its real model via ``get_status()``; simpler modules only
    have their id ("camera.opencv.1"), which becomes a readable label."""
    if cameras is None:
        return "", ""
    cam = getattr(cameras, "capture_camera", None) or getattr(cameras, "active_camera", None)
    model = ""
    if cam is not None:
        try:
            status = cam.get_status()
            model = str(status.get("model") or "").strip()
        except Exception:
            logger.debug("Camera status unavailable for EXIF", exc_info=True)
    if model in ("", "Connected", "Connected (status unavailable)"):
        model = ""
    if model:
        # The camera named itself — leave Make to whatever it wrote into the file.
        return "", model

    cam_id = getattr(cameras, "capture_id", None) or getattr(cameras, "active_id", "") or ""
    if not cam_id:
        return "", ""
    parts = cam_id.split(".")                 # camera.<type>[.<device index>]
    kind = parts[1] if len(parts) > 1 else cam_id
    model = _CAMERA_LABELS.get(kind, kind)
    if len(parts) > 2:
        model += f" #{'.'.join(parts[2:])}"
    return SOFTWARE, model


# ── EXIF assembly ─────────────────────────────────────────────────────────

_ASCII_FOLD = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
               "ß": "ss", "–": "-", "—": "-", "„": '"', "“": '"', "”": '"', "’": "'"}


def _ascii(text: str) -> str:
    """EXIF ASCII tags cannot hold umlauts — transliterate instead of losing them.

    The exact text still ends up in the UTF-16 XP*/UserComment tags.
    """
    for src, dst in _ASCII_FOLD.items():
        text = text.replace(src, dst)
    return text.encode("ascii", "replace").decode("ascii")


def _encode_comment(text: str) -> bytes:
    """EXIF UserComment: 8-byte character-code prefix + payload."""
    try:
        return b"ASCII\x00\x00\x00" + text.encode("ascii")
    except UnicodeEncodeError:
        return b"UNICODE\x00" + text.encode("utf-16-le")


def _xp(text: str) -> bytes:
    """Windows XP* tags are NUL-terminated UTF-16-LE byte strings."""
    return text.encode("utf-16-le") + b"\x00\x00"


def _dms(value: float):
    from PIL.TiffImagePlugin import IFDRational

    v = abs(float(value))
    deg = int(v)
    minutes_f = (v - deg) * 60
    minutes = int(minutes_f)
    seconds = (minutes_f - minutes) * 60
    return (IFDRational(deg, 1), IFDRational(minutes, 1),
            IFDRational(round(seconds * 10000), 10000))


def _local(dt: datetime) -> tuple[datetime, str]:
    """Naive-UTC -> (local datetime, '+02:00' style offset)."""
    aware = dt.replace(tzinfo=timezone.utc).astimezone()
    off = aware.utcoffset() or timezone.utc.utcoffset(aware)
    total = int(off.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return aware, f"{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}"


def build_exif(meta: FileMeta, captured_at: datetime | None = None, base: Any = None):
    """Return a ``PIL.Image.Exif`` with *meta* merged into *base*.

    Values already present in *base* (i.e. written by the camera) win for
    Make/Model — everything else is ours.
    """
    from PIL import Image
    from PIL.TiffImagePlugin import IFDRational

    exif = base if base is not None else Image.Exif()
    captured_at = captured_at or datetime.utcnow()
    local_dt, offset = _local(captured_at)
    stamp = local_dt.strftime("%Y:%m:%d %H:%M:%S")

    exif[_IMAGE_DESCRIPTION] = _ascii(meta.description())
    exif[_SOFTWARE_TAG] = _ascii(meta.software)
    exif[_DATETIME] = stamp
    if meta.artist:
        exif[_ARTIST] = _ascii(meta.artist)
    if meta.copyright:
        exif[_COPYRIGHT] = _ascii(meta.copyright)
    if meta.camera_make and not exif.get(_MAKE):
        exif[_MAKE] = _ascii(meta.camera_make)
    if meta.camera_model and not exif.get(_MODEL):
        exif[_MODEL] = _ascii(meta.camera_model)

    ifd = exif.get_ifd(_EXIF_IFD)
    ifd.setdefault(_DATETIME_ORIGINAL, stamp)
    ifd.setdefault(_DATETIME_DIGITIZED, stamp)
    ifd[_OFFSET_TIME] = offset
    ifd.setdefault(_OFFSET_TIME_ORIGINAL, offset)
    ifd.setdefault(_OFFSET_TIME_DIGITIZED, offset)
    ifd[_USER_COMMENT] = _encode_comment(meta.long_comment())
    if meta.event_name:
        ifd[_XP_TITLE] = _xp(meta.event_name)
    if meta.location_name:
        ifd[_XP_SUBJECT] = _xp(meta.location_name)
    ifd[_XP_COMMENT] = _xp(meta.long_comment())
    exif[_EXIF_IFD] = ifd

    if meta.has_gps or meta.location_name:
        gps = exif.get_ifd(_GPS_IFD)
        gps[_GPS_VERSION] = b"\x02\x03\x00\x00"
        if meta.has_gps:
            gps[_GPS_LAT_REF] = "N" if meta.latitude >= 0 else "S"
            gps[_GPS_LAT] = _dms(meta.latitude)
            gps[_GPS_LON_REF] = "E" if meta.longitude >= 0 else "W"
            gps[_GPS_LON] = _dms(meta.longitude)
            gps[_GPS_MAP_DATUM] = "WGS-84"
            gps[_GPS_DATESTAMP] = captured_at.strftime("%Y:%m:%d")
            gps[_GPS_TIMESTAMP] = (IFDRational(captured_at.hour, 1),
                                   IFDRational(captured_at.minute, 1),
                                   IFDRational(captured_at.second, 1))
            # The position was typed in / taken from the admin device, not measured
            # by this camera — say so rather than implying a GPS fix.
            gps[_GPS_PROCESSING] = _encode_comment("MANUAL")
        if meta.altitude is not None:
            gps[_GPS_ALT_REF] = 0 if meta.altitude >= 0 else 1
            gps[_GPS_ALT] = IFDRational(round(abs(meta.altitude) * 100), 100)
        if meta.location_name:
            gps[_GPS_AREA_INFO] = _encode_comment(meta.location_name)
        exif[_GPS_IFD] = gps

    return exif


def exif_bytes(meta: FileMeta, captured_at: datetime | None = None,
               base: Any = None) -> bytes | None:
    """Serialised EXIF blob (``Exif\\0\\0`` + TIFF), or None if it won't fit."""
    try:
        blob = build_exif(meta, captured_at, base).tobytes()
    except Exception:
        logger.exception("Could not build EXIF block")
        return None
    if len(blob) > _MAX_APP1:
        logger.warning("EXIF block too large (%d bytes) — skipped", len(blob))
        return None
    return blob


# ── JPEG splicing (no re-encode) ──────────────────────────────────────────

def _read_exif(data: bytes):
    """Existing EXIF of a JPEG byte string as a ``PIL.Image.Exif`` (may be empty)."""
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as im:
            exif = im.getexif()
            # Force the sub-IFDs to load while the file is still open.
            exif.get_ifd(_EXIF_IFD)
            exif.get_ifd(_GPS_IFD)
            return exif
    except Exception:
        logger.debug("No readable EXIF in source JPEG", exc_info=True)
        return None


def _splice_app1(data: bytes, payload: bytes) -> bytes | None:
    """Replace/insert the EXIF APP1 segment in a JPEG without touching pixels."""
    if data[:2] != b"\xff\xd8":
        return None
    segment = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload

    out = bytearray(b"\xff\xd8")
    i, n, inserted = 2, len(data), False
    while i + 3 < n:
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        if marker == 0xDA:  # start of scan — everything after is entropy-coded
            break
        if marker == 0xD8 or marker == 0x01 or 0xD0 <= marker <= 0xD7:
            out += data[i:i + 2]
            i += 2
            continue
        seg_len = int.from_bytes(data[i + 2:i + 4], "big")
        if seg_len < 2 or i + 2 + seg_len > n:
            return None
        if marker == 0xE1 and data[i + 4:i + 10] == b"Exif\x00\x00":
            i += 2 + seg_len  # drop the old EXIF, ours replaces it
            continue
        if not inserted and marker != 0xE0:  # keep APP0/JFIF first, then ours
            out += segment
            inserted = True
        out += data[i:i + 2 + seg_len]
        i += 2 + seg_len
    if not inserted:
        out += segment
    out += data[i:]
    return bytes(out)


def tag_jpeg_bytes(data: bytes, meta: FileMeta,
                   captured_at: datetime | None = None) -> bytes:
    """Return *data* with our metadata merged in. Falls back to *data* on error."""
    try:
        blob = exif_bytes(meta, captured_at, base=_read_exif(data))
        if not blob:
            return data
        spliced = _splice_app1(data, blob)
        return spliced if spliced is not None else data
    except Exception:
        logger.exception("EXIF tagging failed — writing file untagged")
        return data


def tag_jpeg_file(path: Path, meta: FileMeta,
                  captured_at: datetime | None = None) -> bool:
    """Tag an already written JPEG in place. Returns True when it changed."""
    try:
        data = path.read_bytes()
    except OSError:
        return False
    tagged = tag_jpeg_bytes(data, meta, captured_at)
    if tagged is data or tagged == data:
        return False
    try:
        path.write_bytes(tagged)
        return True
    except OSError:
        logger.exception("Could not write tagged JPEG %s", path)
        return False


def inherited_exif(path: Path) -> bytes | None:
    """The raw EXIF blob of *path*, to hand to ``Image.save(exif=...)``.

    Used so derived files (thumbnails) carry the same metadata as their source
    without rebuilding it.
    """
    from PIL import Image

    try:
        with Image.open(path) as img:
            return img.info.get("exif")
    except Exception:
        return None


# ── GIF ───────────────────────────────────────────────────────────────────

def gif_comment(meta: FileMeta, captured_at: datetime | None = None) -> bytes:
    """GIF comment-extension payload (GIF has no EXIF).

    Pillow only writes the comment when it is at most 255 bytes, so the text is
    truncated on a UTF-8 character boundary.
    """
    captured_at = captured_at or datetime.utcnow()
    local_dt, _ = _local(captured_at)
    text = f"{meta.long_comment()}; Aufnahme: {local_dt:%Y-%m-%d %H:%M:%S}"
    raw = text.encode("utf-8")
    if len(raw) > 255:
        raw = raw[:255]
        while raw and (raw[-1] & 0xC0) == 0x80:  # don't cut a UTF-8 sequence
            raw = raw[:-1]
        # a truncated lead byte would also be invalid
        if raw and (raw[-1] & 0x80):
            raw = raw[:-1]
    return raw
