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
           jpeg_quality: int = 90) -> dict[str, Any]:
    """Render *template* with *photo_paths* into *out_path* (JPEG)."""
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

    # 2) Photos into slots
    for i, slot in enumerate(slots):
        if i >= len(photo_paths):
            break
        src = photo_paths[i]
        if not src or not Path(src).exists():
            continue
        try:
            with Image.open(src) as pimg:
                pimg = pimg.convert("RGBA")
                fitted = _fit_image(pimg, slot["w"], slot["h"], slot.get("fit", "cover"))
            # Rotate around the slot's centre (expand grows the image, so
            # re-centre it on the slot midpoint instead of the top-left corner)
            cx = int(slot["x"]) + int(slot["w"]) // 2
            cy = int(slot["y"]) + int(slot["h"]) // 2
            rot = slot.get("rotation", 0)
            if rot:
                fitted = fitted.rotate(-rot, expand=True, resample=Image.BICUBIC)
            px = cx - fitted.width // 2
            py = cy - fitted.height // 2
            canvas.alpha_composite(fitted.convert("RGBA"), (px, py))
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
    flat.save(out_path, "JPEG", quality=jpeg_quality)
    return {"path": str(out_path), "width": cw, "height": ch, "slots": len(slots)}


def make_placeholder(slot_index: int, w: int, h: int):
    """A numbered, colored tile used for template previews without real photos."""
    from PIL import Image, ImageDraw

    colors = [(91, 155, 213), (237, 125, 49), (112, 173, 71),
              (255, 192, 0), (165, 105, 189), (39, 174, 160)]
    color = colors[slot_index % len(colors)]
    img = Image.new("RGB", (max(1, int(w)), max(1, int(h))), color)
    draw = ImageDraw.Draw(img)
    label = str(slot_index + 1)
    draw.text((img.width // 2 - 10, img.height // 2 - 20), label, fill="white")
    return img
