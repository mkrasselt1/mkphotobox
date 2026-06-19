"""Collage / framed-layout rendering with Pillow.

One renderer for both editor modes — a template always carries explicit photo
*slots* (canvas pixels). Render order:

    background image  ->  photos into slots  ->  full-canvas frame overlay
    ->  positioned overlays (logos/stickers)  ->  flatten to JPEG
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from app.config import get_config

logger = logging.getLogger(__name__)


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
