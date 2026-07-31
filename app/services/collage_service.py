"""Collage / framed-layout rendering with Pillow.

One renderer for both editor modes — a template always carries explicit photo
*slots* (canvas pixels). Render order:

    background image  ->  photos into slots  ->  full-canvas frame overlay
    ->  positioned overlays (logos/stickers)  ->  flatten to JPEG
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from app.config import get_config

logger = logging.getLogger(__name__)


# ── Fonts ──────────────────────────────────────────────────────────────────
# Label -> candidate filenames per style. We match against whatever is installed
# (DejaVu ships with most Linux distros; Liberation/Arial are common fallbacks).
FONT_FILES: dict[str, dict[str, list[str]]] = {
    "Sans": {
        "regular": ["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Arial.ttf", "arial.ttf"],
        "bold": ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "arialbd.ttf"],
        "italic": ["DejaVuSans-Oblique.ttf", "LiberationSans-Italic.ttf", "ariali.ttf"],
        "bolditalic": ["DejaVuSans-BoldOblique.ttf", "LiberationSans-BoldItalic.ttf", "arialbi.ttf"],
    },
    "Serif": {
        "regular": ["DejaVuSerif.ttf", "LiberationSerif-Regular.ttf", "times.ttf"],
        "bold": ["DejaVuSerif-Bold.ttf", "LiberationSerif-Bold.ttf", "timesbd.ttf"],
        "italic": ["DejaVuSerif-Italic.ttf", "LiberationSerif-Italic.ttf", "timesi.ttf"],
        "bolditalic": ["DejaVuSerif-BoldItalic.ttf", "LiberationSerif-BoldItalic.ttf", "timesbi.ttf"],
    },
    "Mono": {
        "regular": ["DejaVuSansMono.ttf", "LiberationMono-Regular.ttf", "cour.ttf"],
        "bold": ["DejaVuSansMono-Bold.ttf", "LiberationMono-Bold.ttf", "courbd.ttf"],
        "italic": ["DejaVuSansMono-Oblique.ttf", "LiberationMono-Italic.ttf", "couri.ttf"],
        "bolditalic": ["DejaVuSansMono-BoldOblique.ttf", "LiberationMono-BoldItalic.ttf", "courbi.ttf"],
    },
    "Ubuntu": {
        "regular": ["Ubuntu-R.ttf"], "bold": ["Ubuntu-B.ttf"],
        "italic": ["Ubuntu-RI.ttf"], "bolditalic": ["Ubuntu-BI.ttf"],
    },
    "Comic": {
        "regular": ["ComicNeue-Regular.ttf", "comic.ttf", "Comic Sans MS.ttf"],
        "bold": ["ComicNeue-Bold.ttf", "comicbd.ttf"],
        "italic": ["ComicNeue-Italic.ttf"], "bolditalic": ["ComicNeue-BoldItalic.ttf"],
    },
    # ── Script / handwriting (flowing) — install via scripts/install-fonts.sh ──
    "Pacifico": {"regular": ["Pacifico-Regular.ttf", "Pacifico.ttf"]},
    "Dancing Script": {"regular": ["DancingScript-Regular.ttf", "DancingScript[wght].ttf"],
                       "bold": ["DancingScript-Bold.ttf"]},
    "Great Vibes": {"regular": ["GreatVibes-Regular.ttf"]},
    "Lobster": {"regular": ["Lobster-Regular.ttf"]},
    "Sacramento": {"regular": ["Sacramento-Regular.ttf"]},
    "Satisfy": {"regular": ["Satisfy-Regular.ttf"]},
    "Parisienne": {"regular": ["Parisienne-Regular.ttf"]},
}

_FONT_INDEX: Optional[dict[str, Path]] = None


def _font_dirs() -> list[Path]:
    dirs = [
        Path(__file__).resolve().parent.parent / "assets" / "fonts",  # bundled
        Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
        Path.home() / ".fonts" if Path.home() else None,
        Path("/Library/Fonts"), Path("/System/Library/Fonts"),
    ]
    win = os.environ.get("WINDIR")
    if win:
        dirs.append(Path(win) / "Fonts")
    return [d for d in dirs if d and d.exists()]


def _font_index() -> dict[str, Path]:
    """Build (once) a lowercase-filename -> path index of installed fonts."""
    global _FONT_INDEX
    if _FONT_INDEX is not None:
        return _FONT_INDEX
    idx: dict[str, Path] = {}
    for d in _font_dirs():
        for ext in ("*.ttf", "*.otf"):
            try:
                for p in d.rglob(ext):
                    idx.setdefault(p.name.lower(), p)
            except Exception:
                continue
    _FONT_INDEX = idx
    return idx


def _resolve_font_file(filenames: list[str]) -> Optional[Path]:
    idx = _font_index()
    for fn in filenames:
        p = idx.get(fn.lower())
        if p:
            return p
    return None


def available_fonts() -> list[str]:
    """Font labels whose regular variant resolves on this system."""
    out = [label for label, spec in FONT_FILES.items() if _resolve_font_file(spec["regular"])]
    return out or ["Sans"]


def _load_font(label: str, size: int, bold: bool = False, italic: bool = False):
    from PIL import ImageFont

    size = max(6, int(size))
    spec = FONT_FILES.get(label) or FONT_FILES["Sans"]
    if bold and italic:
        order = ["bolditalic", "bold", "italic", "regular"]
    elif bold:
        order = ["bold", "regular"]
    elif italic:
        order = ["italic", "regular"]
    else:
        order = ["regular"]
    for variant in order:
        p = _resolve_font_file(spec.get(variant, []))
        if p:
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    p = _resolve_font_file(FONT_FILES["Sans"]["regular"])
    if p:
        try:
            return ImageFont.truetype(str(p), size)
        except Exception:
            pass
    return ImageFont.load_default()


def _wrap_lines(draw, text: str, font, max_w: int) -> list[str]:
    """Word-wrap *text* to *max_w* px, honouring explicit newlines."""
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        if not paragraph:
            lines.append("")
            continue
        cur = ""
        for word in paragraph.split(" "):
            trial = (cur + " " + word).strip()
            if not cur or draw.textlength(trial, font=font) <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def _render_text_item(item: dict[str, Any]):
    """Render one text element to a transparent RGBA layer (box-sized)."""
    from PIL import Image, ImageDraw

    w = max(1, int(item.get("w", 100)))
    h = max(1, int(item.get("h", 50)))
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    font = _load_font(item.get("font", "Sans"), int(item.get("size", 48)),
                      bool(item.get("bold")), bool(item.get("italic")))
    text = str(item.get("text", ""))
    color = item.get("color", "#000000") or "#000000"
    align = item.get("align", "center")
    valign = item.get("valign", "middle")
    stroke_w = int(item.get("stroke_width", 0) or 0)
    stroke_color = item.get("stroke_color", "#ffffff") or "#ffffff"

    lines = _wrap_lines(draw, text, font, w)
    asc, desc = font.getmetrics()
    line_h = asc + desc
    total_h = line_h * len(lines)
    if valign == "top":
        y = 0
    elif valign == "bottom":
        y = max(0, h - total_h)
    else:
        y = max(0, (h - total_h) // 2)

    for line in lines:
        lw = draw.textlength(line, font=font)
        if align == "left":
            x = 0
        elif align == "right":
            x = max(0, w - lw)
        else:
            x = max(0, (w - lw) / 2)
        draw.text((x, y), line, font=font, fill=color,
                  stroke_width=stroke_w, stroke_fill=stroke_color)
        y += line_h
    return layer


def make_grid_slots(rows: int, cols: int, canvas_w: int, canvas_h: int,
                    margin: int = 40, gap: int = 20) -> list[dict[str, Any]]:
    """Generate evenly spaced photo slots for a rows×cols grid."""
    rows = max(1, rows)
    cols = max(1, cols)
    avail_w = canvas_w - 2 * margin - (cols - 1) * gap
    avail_h = canvas_h - 2 * margin - (rows - 1) * gap
    cell_w = avail_w / cols
    cell_h = avail_h / rows
    slots = []
    for r in range(rows):
        for c in range(cols):
            slots.append({
                "x": round(margin + c * (cell_w + gap)),
                "y": round(margin + r * (cell_h + gap)),
                "w": round(cell_w),
                "h": round(cell_h),
                "rotation": 0,
                "fit": "cover",
            })
    return slots


def _assets_root() -> Path:
    return Path(get_config()["photos"]["storage_path"]).parent / "assets"


def _fit_image(img, w: int, h: int, fit: str):
    """Return a w×h crop/pad of img using cover (fill+crop) or contain."""
    from PIL import Image

    w, h = max(1, int(w)), max(1, int(h))
    src_ratio = img.width / img.height
    dst_ratio = w / h

    if fit == "contain":
        if src_ratio > dst_ratio:
            new_w, new_h = w, round(w / src_ratio)
        else:
            new_w, new_h = round(h * src_ratio), h
        resized = img.resize((max(1, new_w), max(1, new_h)), Image.LANCZOS)
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        canvas.paste(resized, ((w - new_w) // 2, (h - new_h) // 2))
        return canvas

    # cover: scale to fill, center-crop
    if src_ratio > dst_ratio:
        new_h = h
        new_w = round(h * src_ratio)
    else:
        new_w = w
        new_h = round(w / src_ratio)
    resized = img.resize((max(1, new_w), max(1, new_h)), Image.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return resized.crop((left, top, left + w, top + h))


def _open_asset(asset_id: Optional[int]):
    """Open an asset image by id as RGBA, or None."""
    if not asset_id:
        return None
    from PIL import Image

    from app.database import get_engine
    from app.models import Asset
    from sqlmodel import Session

    with Session(get_engine()) as session:
        asset = session.get(Asset, asset_id)
        if asset is None:
            return None
        path = _assets_root() / asset.filename
    if not path.exists():
        return None
    try:
        return Image.open(path).convert("RGBA")
    except Exception:
        logger.exception("Could not open asset %s", asset_id)
        return None


def render(template: dict[str, Any], photo_paths: list[str], out_path: Path,
           jpeg_quality: int = 90, exif: bytes | None = None) -> dict[str, Any]:
    """Render *template* with *photo_paths* into *out_path* (JPEG).

    ``exif`` is an optional serialised EXIF block (see
    :mod:`app.services.exif_service`) written into the result."""
    from PIL import Image

    cw = int(template.get("canvas_width", 1200))
    ch = int(template.get("canvas_height", 1800))
    definition = template.get("definition_json", {})
    if isinstance(definition, str):
        definition = json.loads(definition or "{}")
    slots = definition.get("slots", [])
    overlays = definition.get("overlays", [])
    texts = definition.get("texts", [])

    canvas = Image.new("RGBA", (cw, ch), (255, 255, 255, 255))

    # 1) Background
    bg = _open_asset(template.get("background_asset_id"))
    if bg is not None:
        canvas.alpha_composite(_fit_image(bg, cw, ch, "cover").convert("RGBA"))

    # 2) Photos into slots. A slot may reference an earlier shot via
    # ``photo_index`` (default = its own position), so the same photo can appear
    # in several slots (e.g. 2 shots filling a 3-slot layout).
    for i, slot in enumerate(slots):
        try:
            idx = int(slot.get("photo_index", i))
        except (TypeError, ValueError):
            idx = i
        if idx < 0 or idx >= len(photo_paths):
            continue
        src = photo_paths[idx]
        if not src or not Path(src).exists():
            continue
        try:
            sw, sh = int(slot["w"]), int(slot["h"])
            with Image.open(src) as pimg:
                pimg = pimg.convert("RGBA")
                fitted = _fit_image(pimg, sw, sh, slot.get("fit", "cover"))
            # Rotate around the slot's centre (expand grows the image, so
            # re-centre it on the slot midpoint instead of the top-left corner)
            cx = int(slot["x"]) + sw // 2
            cy = int(slot["y"]) + sh // 2
            rot = slot.get("rotation", 0)
            if rot:
                fitted = fitted.rotate(-rot, expand=True, resample=Image.BICUBIC)
            fitted = fitted.convert("RGBA")
            if slot.get("clip", True):
                # Clip overflow to the slot rectangle: paste the (centred,
                # possibly rotated) image into a slot-sized tile — PIL clips to
                # the tile bounds — then composite the tile at the slot origin.
                tile = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
                tile.alpha_composite(fitted, (sw // 2 - fitted.width // 2,
                                              sh // 2 - fitted.height // 2))
                canvas.alpha_composite(tile, (int(slot["x"]), int(slot["y"])))
            else:
                canvas.alpha_composite(fitted, (cx - fitted.width // 2,
                                                cy - fitted.height // 2))
        except Exception:
            logger.exception("Failed to place photo in slot %d", i)

    # 3) Full-canvas frame overlay
    frame = _open_asset(template.get("overlay_asset_id"))
    if frame is not None:
        canvas.alpha_composite(_fit_image(frame, cw, ch, "cover").convert("RGBA"))

    # 4) Positioned overlays (logos / stickers)
    for ov in overlays:
        img = _open_asset(ov.get("asset_id"))
        if img is None:
            continue
        w, h = int(ov.get("w", img.width)), int(ov.get("h", img.height))
        placed = _fit_image(img, w, h, "contain")
        cx = int(ov.get("x", 0)) + w // 2
        cy = int(ov.get("y", 0)) + h // 2
        rot = ov.get("rotation", 0)
        if rot:
            placed = placed.rotate(-rot, expand=True, resample=Image.BICUBIC)
        canvas.alpha_composite(placed.convert("RGBA"), (cx - placed.width // 2, cy - placed.height // 2))

    # 5) Text elements (rendered on top of everything)
    for txt in texts:
        try:
            layer = _render_text_item(txt)
            cx = int(txt.get("x", 0)) + int(txt.get("w", 0)) // 2
            cy = int(txt.get("y", 0)) + int(txt.get("h", 0)) // 2
            rot = txt.get("rotation", 0)
            if rot:
                layer = layer.rotate(-rot, expand=True, resample=Image.BICUBIC)
            canvas.alpha_composite(layer, (cx - layer.width // 2, cy - layer.height // 2))
        except Exception:
            logger.exception("Failed to render text element")

    # Flatten onto white and save JPEG
    out_path.parent.mkdir(parents=True, exist_ok=True)
    flat = Image.new("RGB", canvas.size, (255, 255, 255))
    flat.paste(canvas, mask=canvas.split()[-1])
    flat.save(out_path, "JPEG", quality=jpeg_quality, **({"exif": exif} if exif else {}))
    return {"path": str(out_path), "width": cw, "height": ch, "slots": len(slots)}


def render_set_gif(photo_paths: list[str], out_path: Path,
                   max_size: int = 700, duration_ms: int = 800,
                   comment: bytes | None = None) -> Optional[Path]:
    """Build an animated GIF cycling through a set's individual shots.

    Each shot is scaled to fit a common max_size square and centred on white so
    frames share one canvas size (required for a clean animated GIF). Returns the
    written path, or None if there aren't at least 2 usable frames."""
    from PIL import Image

    srcs = [p for p in photo_paths if p and Path(p).exists()]
    if len(srcs) < 2:
        return None

    # Frame canvas = max aspect across shots, capped to max_size on the long edge.
    frames = []
    for p in srcs:
        try:
            img = Image.open(p).convert("RGB")
        except Exception:
            continue
        scale = min(max_size / img.width, max_size / img.height, 1.0)
        frames.append(img.resize((max(1, round(img.width * scale)),
                                  max(1, round(img.height * scale))), Image.LANCZOS))
    if len(frames) < 2:
        return None

    cw = max(f.width for f in frames)
    ch = max(f.height for f in frames)
    canvases = []
    for f in frames:
        canvas = Image.new("RGB", (cw, ch), (255, 255, 255))
        canvas.paste(f, ((cw - f.width) // 2, (ch - f.height) // 2))
        canvases.append(canvas)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        canvases[0].save(out_path, "GIF", save_all=True, append_images=canvases[1:],
                         duration=duration_ms, loop=0, optimize=True, disposal=2,
                         **({"comment": comment} if comment else {}))
        return out_path
    except Exception:
        logger.exception("Set GIF creation failed")
        return None


# Backdrop per shot — a different colour per placeholder makes it obvious at a
# glance which slot holds which shot, without printing a number into the corner.
PLACEHOLDER_COLORS = [
    ((44, 84, 140), (91, 155, 213)),
    ((150, 70, 22), (237, 125, 49)),
    ((52, 104, 40), (112, 173, 71)),
    ((150, 110, 0), (255, 192, 0)),
    ((92, 52, 120), (165, 105, 189)),
    ((16, 96, 92), (39, 174, 160)),
]
PLACEHOLDER_SKIN = [(232, 190, 160), (208, 158, 122), (166, 116, 84), (120, 82, 60)]

#: Placeholders are drawn at a camera-like aspect, never at the slot's aspect.
PLACEHOLDER_ASPECT = 4 / 3


def make_placeholder(slot_index: int, w: int | None = None, h: int | None = None,
                     *, long_edge: int = 900):
    """A photo-like stand-in for a shot that hasn't been taken yet.

    Deliberately rendered at **camera aspect**, not at the slot's aspect: the
    renderer then crops it exactly like a real photo, so a template preview shows
    how much of a shot each slot actually keeps. Filling the slot exactly (which
    is what passing the slot size would do) would hide precisely that.

    ``w``/``h`` are the slot's pixel size and only nudge the resolution — a tiny
    slot doesn't need a 900 px stand-in.

    The number sits on the figure's face, roughly in the middle of the frame, so
    it survives whatever the crop does to the edges.
    """
    from PIL import Image, ImageDraw

    if w and h:
        long_edge = max(240, min(long_edge, round(max(int(w), int(h)) * 1.4)))
    pw = max(120, int(long_edge))
    ph = max(90, round(pw / PLACEHOLDER_ASPECT))

    dark, light = PLACEHOLDER_COLORS[slot_index % len(PLACEHOLDER_COLORS)]
    img = Image.new("RGB", (pw, ph), dark)
    draw = ImageDraw.Draw(img)
    for y in range(ph):
        t = (y / ph) ** 1.3
        draw.line([(0, y), (pw, y)],
                  fill=tuple(round(dark[c] + (light[c] - dark[c]) * t) for c in range(3)))

    # ── Stand-in guest: shoulders, neck, head, hair ──────────────────────
    skin = PLACEHOLDER_SKIN[slot_index % len(PLACEHOLDER_SKIN)]
    cx = pw // 2
    head_r = round(ph * 0.22)
    head_cy = round(ph * 0.42)
    body_w = round(head_r * 3.4)
    body_top = head_cy + round(head_r * 1.45)

    draw.rounded_rectangle([cx - body_w // 2, body_top, cx + body_w // 2, ph + head_r],
                           radius=round(head_r * 1.1), fill=(246, 246, 250))
    neck = round(head_r * 0.34)
    draw.rectangle([cx - neck, head_cy, cx + neck, body_top + neck], fill=skin)
    draw.ellipse([cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r], fill=skin)
    # Hair as a cap that stops well above the eyes
    draw.chord([cx - head_r, head_cy - head_r, cx + head_r, head_cy + round(head_r * 0.45)],
               180, 360, fill=(58, 44, 38))

    # ── The shot number, big, across the face ────────────────────────────
    label = str(slot_index + 1)
    font = _load_font("Sans", max(14, round(head_r * 1.5)), bold=True)
    left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
    draw.text((cx - (right - left) / 2 - left, head_cy - (bottom - top) / 2 - top),
              label, font=font, fill=(255, 255, 255),
              stroke_width=max(2, round(head_r * 0.09)), stroke_fill=(30, 30, 40))
    return img
