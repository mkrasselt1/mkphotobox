"""Looks — colour filters the guests pick before the shot.

Every look is defined twice, and that is the whole point:

``css``
    What the booth puts on the live ``<video>`` / ``<img>`` so guests see the
    look *before* they pose. Costs nothing — the browser's compositor does it.

``apply``
    What the server does to the captured JPEG. This is the one that is kept.

The two are tuned to match. They are different engines, so it is an
approximation, not a pixel-identical result — close enough that nobody is
surprised by what comes out of the printer.

The filter is baked into the photo on purpose: it has to survive into the
collage, the print, the USB export and the guest's download alike.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_FILTER = "none"


def _identity(img):
    return img


def _grayscale(img):
    from PIL import ImageOps

    return ImageOps.grayscale(img).convert("RGB")


def _matrix(img, matrix: tuple[float, ...]):
    """Apply a 3x4 colour matrix (the fast path — one C-level pass)."""
    return img.convert("RGB", matrix)


def _sepia(img):
    # Classic sepia matrix, slightly toned down so faces don't go orange.
    return _matrix(img, (
        0.393, 0.769, 0.189, 0,
        0.349, 0.686, 0.168, 0,
        0.272, 0.534, 0.131, 0,
    ))


def _vintage(img):
    from PIL import ImageEnhance

    img = _matrix(img, (
        0.32, 0.55, 0.13, 12,
        0.28, 0.58, 0.14, 6,
        0.24, 0.46, 0.20, 20,
    ))
    return ImageEnhance.Contrast(img).enhance(1.12)


def _warm(img):
    from PIL import ImageEnhance

    img = _matrix(img, (
        1.08, 0.00, 0.00, 6,
        0.00, 1.02, 0.00, 2,
        0.00, 0.00, 0.92, 0,
    ))
    return ImageEnhance.Color(img).enhance(1.12)


def _cool(img):
    from PIL import ImageEnhance

    img = _matrix(img, (
        0.92, 0.00, 0.00, 0,
        0.00, 1.00, 0.00, 2,
        0.00, 0.00, 1.10, 8,
    ))
    return ImageEnhance.Color(img).enhance(1.08)


def _pop(img):
    from PIL import ImageEnhance

    img = ImageEnhance.Color(img).enhance(1.45)
    return ImageEnhance.Contrast(img).enhance(1.18)


def _high_contrast_bw(img):
    from PIL import ImageEnhance, ImageOps

    img = ImageOps.grayscale(img).convert("RGB")
    return ImageEnhance.Contrast(img).enhance(1.5)


#: id -> {label (German, shown in the booth), css, apply}
FILTERS: dict[str, dict[str, Any]] = {
    "none":     {"label": "Original",   "css": "",                                              "apply": _identity},
    "bw":       {"label": "Schwarzweiß", "css": "grayscale(1)",                                  "apply": _grayscale},
    "noir":     {"label": "Noir",       "css": "grayscale(1) contrast(1.5)",                     "apply": _high_contrast_bw},
    "sepia":    {"label": "Sepia",      "css": "sepia(0.85)",                                    "apply": _sepia},
    "vintage":  {"label": "Vintage",    "css": "sepia(0.45) contrast(1.12) saturate(0.85)",      "apply": _vintage},
    "warm":     {"label": "Warm",       "css": "saturate(1.12) sepia(0.15) brightness(1.03)",    "apply": _warm},
    "cool":     {"label": "Kühl",       "css": "saturate(1.08) hue-rotate(8deg) brightness(1.02)", "apply": _cool},
    "pop":      {"label": "Knallig",    "css": "saturate(1.45) contrast(1.18)",                  "apply": _pop},
}


def is_enabled(cfg: dict | None) -> bool:
    if not isinstance(cfg, dict):
        return True
    return bool(cfg.get("filters", {}).get("enabled", True))


def available(cfg: dict | None = None) -> list[dict[str, str]]:
    """The looks the booth may offer, in the configured order.

    ``filters.available`` lets an operator cut the list down; unknown ids are
    dropped with a warning rather than breaking the booth. "none" is always
    first — guests must be able to get back to the untouched image.
    """
    ids = ((cfg or {}).get("filters") or {}).get("available")
    if not isinstance(ids, list) or not ids:
        ids = list(FILTERS)
    out, seen = [], set()
    for fid in [DEFAULT_FILTER] + [str(i) for i in ids]:
        if fid in seen:
            continue
        if fid not in FILTERS:
            logger.warning("Unknown photo filter %r in filters.available — ignored", fid)
            continue
        seen.add(fid)
        out.append({"id": fid, "label": FILTERS[fid]["label"], "css": FILTERS[fid]["css"]})
    return out


def resolve(filter_id: Optional[str]) -> Optional[Callable]:
    """The transform for *filter_id*, or None when nothing needs doing."""
    if not filter_id or filter_id == DEFAULT_FILTER:
        return None
    spec = FILTERS.get(filter_id)
    if spec is None:
        logger.warning("Unknown photo filter %r — keeping the original", filter_id)
        return None
    return spec["apply"]


def apply_to_jpeg(data: bytes, filter_id: Optional[str], quality: int = 92) -> bytes:
    """Bake a look into JPEG bytes. Returns *data* unchanged when there is
    nothing to do or anything goes wrong — a filter must never lose a photo."""
    fn = resolve(filter_id)
    if fn is None or not data:
        return data
    import io

    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as src:
            exif = src.info.get("exif")
            img = fn(src.convert("RGB"))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=quality, **({"exif": exif} if exif else {}))
            return buf.getvalue()
    except Exception:
        logger.exception("Filter %r failed — keeping the original photo", filter_id)
        return data
