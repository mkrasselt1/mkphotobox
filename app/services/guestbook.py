"""Guest book — the guests draw or write on their own photo.

After the shot they get a canvas over the picture: scribble a heart, sign their
name, add a greeting. The result is composited into the photo itself so it
survives everywhere the photo goes — print, USB stick, download, online gallery.

The untouched original is kept once, in ``originals/``, and recorded on
``Photo.original_path``. A second doodle on the same photo therefore starts from
the clean image again instead of stacking on top of the first attempt.
"""

from __future__ import annotations

import io
import logging
import shutil
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

ORIGINALS_DIR = "originals"
DEFAULT_MAX_MESSAGE = 120


def is_enabled(cfg: dict | None) -> bool:
    if not isinstance(cfg, dict):
        return True
    return bool(cfg.get("guestbook", {}).get("enabled", True))


def max_message_length(cfg: dict | None) -> int:
    try:
        return int((cfg or {}).get("guestbook", {}).get("max_message_len", DEFAULT_MAX_MESSAGE))
    except (TypeError, ValueError):
        return DEFAULT_MAX_MESSAGE


def preserve_original(storage: Path, filename: str, original_path: Optional[str]) -> str:
    """Make sure an untouched copy exists and return its storage-relative path.

    Called before the first edit. If the photo was already annotated once, the
    stored original is restored so edits never stack."""
    originals = storage / ORIGINALS_DIR
    originals.mkdir(parents=True, exist_ok=True)
    target = originals / filename

    if original_path and (storage / original_path).exists():
        # Second pass — go back to the clean image first.
        shutil.copy2(storage / original_path, storage / filename)
        return original_path

    if not target.exists():
        shutil.copy2(storage / filename, target)
    return f"{ORIGINALS_DIR}/{filename}"


#: Mehr Sticker braucht kein Foto — und jeder kostet beim Rendern Zeit.
MAX_STICKERS = 40


def parse_stickers(raw: str | None) -> list[dict[str, Any]]:
    """Emoji-Sticker aus dem Formularfeld (JSON-Liste) prüfen und normieren.

    Je Sticker: ``emoji``, Mittelpunkt ``x``/``y`` und Kantenlänge ``size``
    jeweils relativ (0..1; size bezogen auf die Fotobreite), ``rotation`` in
    Grad. Unbrauchbares wird still verworfen — ein Sticker darf das Speichern
    der Zeichnung nicht verhindern."""
    import json

    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    out: list[dict[str, Any]] = []
    for s in data if isinstance(data, list) else []:
        if not isinstance(s, dict):
            continue
        emoji = str(s.get("emoji", "")).strip()
        if not emoji or len(emoji) > 16:
            continue
        try:
            x, y = float(s.get("x", 0.5)), float(s.get("y", 0.5))
            size = float(s.get("size", 0.2))
            rot = float(s.get("rotation", 0) or 0)
        except (TypeError, ValueError):
            continue
        out.append({"emoji": emoji,
                    "x": min(1.5, max(-0.5, x)), "y": min(1.5, max(-0.5, y)),
                    "size": min(2.0, max(0.01, size)), "rotation": rot % 360})
        if len(out) >= MAX_STICKERS:
            break
    return out


def apply(photo_file: Path, overlay_png: Optional[bytes], message: str = "",
          *, jpeg_quality: int = 92, font: str = "Sans",
          stickers: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Composite *overlay_png*, emoji *stickers* and an optional *message*
    onto *photo_file*.

    The overlay arrives at whatever resolution the guest's screen had; it is
    scaled to the photo, so a tablet doodle lands correctly on a 24-megapixel
    DSLR frame. Stickers are rendered from vector graphics at the photo's own
    resolution (see :mod:`app.services.emoji_service`), on top of the drawing —
    the same order the guest saw on screen. Returns a small summary for the
    API response.
    """
    from PIL import Image

    with Image.open(photo_file) as src:
        exif = src.info.get("exif")
        base = src.convert("RGBA")

    drew = False
    if overlay_png:
        try:
            with Image.open(io.BytesIO(overlay_png)) as ov:
                overlay = ov.convert("RGBA")
                if overlay.size != base.size:
                    overlay = overlay.resize(base.size, Image.LANCZOS)
                base.alpha_composite(overlay)
                drew = True
        except Exception:
            logger.exception("Guest book overlay could not be applied")

    placed = 0
    if stickers:
        from app.services import emoji_service

        for st in stickers:
            try:
                if emoji_service.place(base, st["emoji"], st["x"] * base.width,
                                       st["y"] * base.height, st["size"] * base.width,
                                       st.get("rotation", 0)):
                    placed += 1
            except Exception:
                logger.exception("Guest book sticker could not be applied")

    message = (message or "").strip()
    if message:
        base.alpha_composite(_message_band(base.size, message, font))

    flat = Image.new("RGB", base.size, (255, 255, 255))
    flat.paste(base, mask=base.split()[-1])
    flat.save(photo_file, "JPEG", quality=jpeg_quality, **({"exif": exif} if exif else {}))
    return {"width": base.width, "height": base.height,
            "drawing": drew, "stickers": placed, "message": bool(message)}


def _message_band(size: tuple[int, int], message: str, font_label: str):
    """A translucent strip along the bottom carrying the guests' greeting.

    Sized relative to the photo so it looks the same on a webcam frame and on a
    full-resolution DSLR file."""
    from PIL import Image, ImageDraw

    from app.services.collage_service import _load_font, _wrap_lines

    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    font_size = max(14, round(h * 0.045))
    pad = max(8, round(h * 0.018))
    font = _load_font(font_label, font_size)
    lines = _wrap_lines(draw, message, font, w - 2 * pad)[:3]  # a greeting, not an essay

    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    band_h = line_h * len(lines) + 2 * pad
    top = h - band_h

    draw.rectangle([0, top, w, h], fill=(0, 0, 0, 130))
    y = top + pad
    for line in lines:
        lw = draw.textlength(line, font=font)
        draw.text(((w - lw) / 2, y), line, font=font, fill=(255, 255, 255, 255),
                  stroke_width=max(1, font_size // 18), stroke_fill=(0, 0, 0, 200))
        y += line_h
    return layer
