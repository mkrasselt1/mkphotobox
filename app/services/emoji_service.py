"""Emojis als hochauflösende Sticker.

Quelle sind die Twemoji-Vektorgrafiken (CC-BY 4.0) unter
``app/assets/emoji/svg/`` — geladen von ``scripts/install-emoji.sh``. Gerendert
wird mit ``resvg-py`` in genau der Zielgröße, damit ein Emoji auch auf einem
300-dpi-Druck scharf bleibt.

Fehlt eins von beiden, gibt es einen Notbehelf über einen Farb-Emoji-Font
(Noto Color Emoji ist ein 136-px-Bitmap — hochskaliert sichtbar weich). Ein
fehlendes Emoji darf nie ein Foto oder eine Collage scheitern lassen.
"""

from __future__ import annotations

import io
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

SVG_DIR = Path(__file__).resolve().parent.parent / "assets" / "emoji" / "svg"

#: Obergrenze für eine Emoji-Kantenlänge — schützt vor versehentlichen
#: 50 000-px-Werten aus einer kaputten Vorlage oder Anfrage.
MAX_EDGE = 6000

#: Gültiger Twemoji-Dateiname (ohne .svg): Hex-Codepoints mit Bindestrich.
_NAME_RE = re.compile(r"^[0-9a-f]{2,6}(-[0-9a-f]{2,6}){0,15}$")

# Farb-Emoji-Fonts für den Notbehelf. Noto Color Emoji (CBDT) lädt Pillow nur in
# der festen Bitmapgröße 109.
_FALLBACK_FONTS = ["NotoColorEmoji.ttf", "seguiemj.ttf", "Apple Color Emoji.ttc"]
_FALLBACK_SIZE = 109


def svg_name(emoji: str) -> str:
    """Twemoji-Dateiname: FE0F fällt weg, außer in ZWJ-Sequenzen."""
    if "‍" not in emoji:
        emoji = emoji.replace("️", "")
    return "-".join(f"{ord(c):x}" for c in emoji)


def svg_path(emoji: str) -> Optional[Path]:
    """SVG-Datei zu einem Emoji, mit den üblichen Varianten als Ausweichweg."""
    emoji = (emoji or "").strip()
    if not emoji or len(emoji) > 16:
        return None
    candidates = [svg_name(emoji),
                  "-".join(f"{ord(c):x}" for c in emoji),                       # mit FE0F
                  "-".join(f"{ord(c):x}" for c in emoji.replace("️", ""))]  # ganz ohne
    for name in candidates:
        p = svg_file(name)
        if p:
            return p
    return None


def svg_file(name: str) -> Optional[Path]:
    """SVG zu einem (bereits berechneten) Dateinamen — nur gültige Namen."""
    name = (name or "").lower()
    if not _NAME_RE.match(name):
        return None
    p = SVG_DIR / f"{name}.svg"
    return p if p.is_file() else None


def _resvg():
    try:
        import resvg_py  # type: ignore
        return resvg_py
    except Exception:
        return None


def status() -> dict[str, Any]:
    """Für den Admin-Bereich: Sind Grafiken und Renderer da?"""
    try:
        count = sum(1 for _ in SVG_DIR.glob("*.svg")) if SVG_DIR.is_dir() else 0
    except OSError:
        count = 0
    version = None
    try:
        version = (SVG_DIR / ".version").read_text().strip() or None
    except OSError:
        pass
    renderer = _resvg() is not None
    return {
        "svg_count": count,
        "version": version,
        "renderer": renderer,
        "high_res": bool(count and renderer),
        "fallback_font": bool(_fallback_font_path()),
        "attribution": "Emoji-Grafiken: Twemoji © Twitter, Inc. und Mitwirkende, CC-BY 4.0",
    }


#: Nur kleinere Emojis cachen: ein 1200-px-Sticker sind schon 5,8 MB RGBA, ein
#: großer Druck-Sticker ein Vielfaches davon — auf einem Pi zu viel für einen Cache.
_CACHE_MAX_EDGE = 1200


@lru_cache(maxsize=24)
def _render_cached(emoji: str, size: int):
    return _render_uncached(emoji, size)


def _render_uncached(emoji: str, size: int):
    p = svg_path(emoji)
    rv = _resvg()
    if p is not None and rv is not None:
        try:
            from PIL import Image

            png = rv.svg_to_bytes(svg_path=str(p), width=size, height=size,
                                  skip_system_fonts=True)
            img = Image.open(io.BytesIO(bytes(png))).convert("RGBA")
            if img.size != (size, size):  # Twemoji ist quadratisch — nur zur Sicherheit
                img = img.resize((size, size), Image.LANCZOS)
            return img
        except Exception:
            logger.exception("Emoji %r: SVG-Rendering fehlgeschlagen", emoji)
    return _render_fallback(emoji, size)


def render(emoji: str, size: int):
    """Emoji als quadratisches RGBA-Bild mit Kantenlänge *size*, oder None.

    Das Ergebnis kommt aus einem kleinen Cache — Aufrufer dürfen es nicht an
    Ort und Stelle verändern (``rotate``/``resize`` liefern ohnehin ein neues Bild)."""
    size = max(8, min(MAX_EDGE, int(size)))
    emoji = (emoji or "").strip()
    if not emoji:
        return None
    if size <= _CACHE_MAX_EDGE:
        return _render_cached(emoji, size)
    return _render_uncached(emoji, size)


@lru_cache(maxsize=1)
def _fallback_font_path() -> Optional[Path]:
    from app.services.collage_service import _font_index

    idx = _font_index()
    for fn in _FALLBACK_FONTS:
        p = idx.get(fn.lower())
        if p:
            return p
    for d in (Path("/usr/share/fonts"), Path("/usr/local/share/fonts")):
        try:
            for p in d.rglob("NotoColorEmoji*.ttf"):
                return p
        except Exception:
            continue
    return None


def _render_fallback(emoji: str, size: int):
    """Notbehelf über einen Farb-Emoji-Font (Bitmap, hochskaliert)."""
    from PIL import Image, ImageDraw, ImageFont

    path = _fallback_font_path()
    if path is None:
        logger.warning("Emoji %r: weder SVG noch Emoji-Font vorhanden", emoji)
        return None
    try:
        font = ImageFont.truetype(str(path), _FALLBACK_SIZE)
    except Exception:
        try:
            font = ImageFont.truetype(str(path), 64)
        except Exception:
            return None
    try:
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        l, t, r, b = probe.textbbox((0, 0), emoji, font=font, embedded_color=True)
        w, h = max(1, r - l), max(1, b - t)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((-l, -t), emoji, font=font, embedded_color=True)
        edge = max(w, h)
        square = Image.new("RGBA", (edge, edge), (0, 0, 0, 0))
        square.alpha_composite(img, ((edge - w) // 2, (edge - h) // 2))
        return square.resize((size, size), Image.LANCZOS)
    except Exception:
        logger.exception("Emoji %r: Font-Notbehelf fehlgeschlagen", emoji)
        return None


def place(canvas, emoji: str, cx: float, cy: float, size: float, rotation: float = 0) -> bool:
    """Emoji mit Mittelpunkt (cx, cy) und Kantenlänge *size* auf *canvas* (RGBA)
    setzen, im Uhrzeigersinn um *rotation* Grad gedreht. True bei Erfolg."""
    from PIL import Image

    img = render(emoji, round(size))
    if img is None:
        return False
    if rotation:
        img = img.rotate(-float(rotation), expand=True, resample=Image.BICUBIC)
    _composite_clipped(canvas, img, cx, cy)
    return True


def _composite_clipped(canvas, img, cx, cy) -> None:
    """alpha_composite verweigert negative Ziele und Überstand — Sticker, die
    über den Rand ragen, werden zugeschnitten statt verworfen."""
    x, y = round(cx - img.width / 2), round(cy - img.height / 2)
    left, top = max(0, -x), max(0, -y)
    right = min(img.width, canvas.width - x)
    bottom = min(img.height, canvas.height - y)
    if right <= left or bottom <= top:
        return
    canvas.alpha_composite(img.crop((left, top, right, bottom)), (x + left, y + top))
