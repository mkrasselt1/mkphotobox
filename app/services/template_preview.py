"""Cached preview images of photo templates.

The booth shows these on the "Layout wählen" cards so guests see the actual
arrangement — frame, slot positions, text — instead of a generic icon. The admin
template list uses the same image.

Rendered with the numbered placeholder tiles, never with real guest photos: the
booth fetches these without a login, and a preview must not become a side channel
to the last shots of the evening.

Cached on disk under a hash of everything that affects the render, so a preview
regenerates itself the moment a template changes and costs nothing in between.
Kept *outside* the photo storage directory — anything in there would be swept up
by the USB export, the CD burn and the gallery.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Long edge of the cached preview. Big enough for a touch card, small enough
#: that a booth with a dozen templates stays instant.
MAX_EDGE = 480
JPEG_QUALITY = 82

_DIR_NAME = "template_previews"


def previews_dir(cfg: dict) -> Path:
    """Sibling of the photo storage — never inside it (see module docstring)."""
    return Path(cfg["photos"]["storage_path"]).parent / _DIR_NAME


#: Bump whenever the *rendering* changes (placeholder look, preview size …).
#: Without this a box that updates its software would keep serving previews drawn
#: by the old code — the templates themselves haven't changed, after all.
RENDER_VERSION = 2


def signature(template: Any) -> str:
    """Short hash over everything that changes the rendered result."""
    raw = json.dumps([
        RENDER_VERSION,
        template.canvas_width,
        template.canvas_height,
        template.background_asset_id,
        template.overlay_asset_id,
        template.definition_json or "{}",
    ], sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def preview_file(cfg: dict, template: Any) -> Path:
    return previews_dir(cfg) / f"{template.id}_{signature(template)}.jpg"


def ensure(cfg: dict, template: Any) -> Path | None:
    """Path to the template's preview, rendering it if it isn't cached yet.

    Returns None when the template cannot be rendered (no slots yet, broken
    definition) — callers fall back to an icon.
    """
    target = preview_file(cfg, template)
    if target.exists():
        return target
    try:
        return _render(cfg, template, target)
    except Exception:
        logger.exception("Could not render preview for template %s", getattr(template, "id", "?"))
        return None


def _render(cfg: dict, template: Any, target: Path) -> Path | None:
    from PIL import Image

    from app.services import collage_service

    try:
        definition = json.loads(template.definition_json or "{}")
    except json.JSONDecodeError:
        definition = {}
    slots = definition.get("slots") or []
    if not slots:
        return None

    # One placeholder per distinct shot, not per slot: a slot may reuse an
    # earlier shot via photo_index, and the numbering should match what the
    # guest is asked for ("Aufnahme 1 von 3"). The size kept here is only the
    # largest slot that shows this shot — it picks the stand-in's resolution,
    # not its aspect (the placeholder is drawn at camera aspect and gets cropped
    # by the renderer, exactly like a real photo would be).
    shots: dict[int, int] = {}
    for i, slot in enumerate(slots):
        try:
            idx = int(slot.get("photo_index", i))
        except (TypeError, ValueError):
            idx = i
        if idx >= 0:
            edge = max(int(slot.get("w", 400) or 400), int(slot.get("h", 300) or 300))
            shots[idx] = max(shots.get(idx, 0), edge)
    if not shots:
        return None

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pb_tplprev_") as tmp:
        tmp_dir = Path(tmp)
        photo_paths: list[str] = []
        for idx in range(max(shots) + 1):
            edge = shots.get(idx, 400)
            p = tmp_dir / f"ph_{idx}.jpg"
            collage_service.make_placeholder(idx, edge, edge).save(p, "JPEG", quality=85)
            photo_paths.append(str(p))

        full = tmp_dir / "full.jpg"
        collage_service.render({
            "canvas_width": template.canvas_width,
            "canvas_height": template.canvas_height,
            "background_asset_id": template.background_asset_id,
            "overlay_asset_id": template.overlay_asset_id,
            "definition_json": definition,
        }, photo_paths, full, jpeg_quality=90)

        with Image.open(full) as img:
            img = img.convert("RGB")
            img.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
            # Write beside the target and move into place, so a second request
            # rendering the same preview can never serve a half-written file.
            staged = target.with_suffix(".tmp.jpg")
            img.save(staged, "JPEG", quality=JPEG_QUALITY)
        os.replace(staged, target)

    _prune(target)
    return target


def _prune(keep: Path) -> None:
    """Drop previews of earlier versions of the same template."""
    template_id = keep.name.split("_", 1)[0]
    for old in keep.parent.glob(f"{template_id}_*.jpg"):
        if old != keep:
            try:
                old.unlink()
            except OSError:
                pass


def delete_for(cfg: dict, template_id: int) -> int:
    """Remove all cached previews of a template (called when it is deleted)."""
    removed = 0
    try:
        for p in previews_dir(cfg).glob(f"{template_id}_*.jpg"):
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    except OSError:
        pass
    return removed
