"""Map a printer's paper/media name to a physical size (mm) — so a print
template's canvas comes from the real paper instead of a pixel guess.

Two sources of truth, tried in order:
  1. Gutenprint / IPP self-describing codes  ``w<pt>h<pt>``  (1/72 inch)
     e.g. ``w288h432`` = 288/72 × 432/72 inch = 4×6".  Handles the long tail
     of dye-sub media (incl. ``…div2`` 2-up panorama splits) automatically.
  2. A lookup table of common named sizes (A-series, US, photo formats).

The physical size lets us compute the canvas pixels at a chosen DPI, which is
what photo printers actually want (e.g. 10×15 cm @ 300 dpi → 1181×1772 px).
"""

from __future__ import annotations

import re
from typing import Optional

MM_PER_INCH = 25.4
PT_PER_INCH = 72.0

# Common named media → (width_mm, height_mm) in *portrait* (short × long).
# Keys are lower-cased and stripped of spaces/underscores for fuzzy matching.
_NAMED_MM: dict[str, tuple[float, float]] = {
    # ISO A series
    "a3": (297.0, 420.0),
    "a4": (210.0, 297.0),
    "a5": (148.0, 210.0),
    "a6": (105.0, 148.0),
    "a7": (74.0, 105.0),
    # US
    "letter": (215.9, 279.4),
    "legal": (215.9, 355.6),
    "tabloid": (279.4, 431.8),
    "ledger": (279.4, 431.8),
    # Photo / dye-sub formats (cm and inch aliases)
    "4x6": (101.6, 152.4),
    "6x4": (101.6, 152.4),
    "10x15": (100.0, 150.0),
    "10x15cm": (100.0, 150.0),
    "5x7": (127.0, 177.8),
    "7x5": (127.0, 177.8),
    "13x18": (130.0, 180.0),
    "13x18cm": (130.0, 180.0),
    "6x8": (152.4, 203.2),
    "8x10": (203.2, 254.0),
    "8x12": (203.2, 304.8),
    "2x6": (50.8, 152.4),       # photo-strip
    "6x9": (152.4, 228.6),
    "6x20": (152.4, 508.0),     # panorama (e.g. CP-3800 dual)
    "15x20": (150.0, 200.0),
    "15x23": (150.0, 230.0),
}


def _norm(name: str) -> str:
    return re.sub(r"[\s_]+", "", (name or "").strip().lower())


def paper_size_mm(name: str) -> Optional[tuple[float, float]]:
    """Return (width_mm, height_mm) in portrait orientation for a media *name*,
    or ``None`` if it can't be resolved."""
    if not name:
        return None
    raw = name.strip()

    # 1) Gutenprint/IPP self-describing code: w<pt>h<pt>[suffix]
    m = re.match(r"^w(\d+(?:\.\d+)?)h(\d+(?:\.\d+)?)", raw, re.IGNORECASE)
    if m:
        w_in = float(m.group(1)) / PT_PER_INCH
        h_in = float(m.group(2)) / PT_PER_INCH
        w_mm, h_mm = w_in * MM_PER_INCH, h_in * MM_PER_INCH
        return (min(w_mm, h_mm), max(w_mm, h_mm))

    key = _norm(raw)

    # 2a) Named table (exact)
    if key in _NAMED_MM:
        return _NAMED_MM[key]

    # 2b) "NxM" / "NxMcm" / "NxMin" patterns not in the table
    m = re.match(r"^(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)(cm|mm|in|inch)?$", key)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        unit = m.group(3) or ""
        if unit in ("in", "inch") or (not unit and a < 30 and b < 30):
            a, b = a * MM_PER_INCH, b * MM_PER_INCH       # inches → mm
        elif unit == "cm" or (not unit):
            a, b = a * 10.0, b * 10.0                      # cm → mm
        # unit == "mm": already mm
        return (min(a, b), max(a, b))

    return None


def px_from_mm(width_mm: float, height_mm: float, dpi: int = 300) -> tuple[int, int]:
    """Pixel dimensions for a physical size at *dpi* (rounded)."""
    dpi = max(1, int(dpi))
    return (
        max(1, round(width_mm / MM_PER_INCH * dpi)),
        max(1, round(height_mm / MM_PER_INCH * dpi)),
    )
