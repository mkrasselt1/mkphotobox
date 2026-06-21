"""Output preset API — reusable print-paper and social-format definitions.

A *print* preset binds a printer + paper (size read from the device) and an
explicit DPI, deriving the canvas pixels from the real physical size. A *social*
preset is just a fixed pixel format (Instagram, TikTok, …). Templates link to a
preset so their canvas follows it and printing routes to the right printer.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.auth import require_role
from app.database import get_session
from app.models import OutputPreset
from app.services.paper_sizes import paper_size_mm, px_from_mm

router = APIRouter(prefix="/api/v1/presets", tags=["presets"])


# Seeded social/digital formats (short × long in px). Always present, not deletable.
BUILTIN_SOCIAL: list[dict] = [
    {"name": "Instagram – Quadrat (1:1)", "width_px": 1080, "height_px": 1080},
    {"name": "Instagram – Hochformat (4:5)", "width_px": 1080, "height_px": 1350},
    {"name": "Instagram / TikTok Story (9:16)", "width_px": 1080, "height_px": 1920},
    {"name": "Quer / YouTube (16:9)", "width_px": 1920, "height_px": 1080},
]


def ensure_builtin_presets(session: Session) -> int:
    """Create the built-in social presets if missing. Returns how many added."""
    added = 0
    for spec in BUILTIN_SOCIAL:
        exists = session.exec(
            select(OutputPreset).where(
                OutputPreset.builtin == True,  # noqa: E712
                OutputPreset.name == spec["name"],
            )
        ).first()
        if exists:
            continue
        session.add(OutputPreset(
            name=spec["name"], kind="social",
            width_px=spec["width_px"], height_px=spec["height_px"],
            builtin=True,
        ))
        added += 1
    if added:
        session.commit()
    return added


def _preset_dict(p: OutputPreset) -> dict:
    d = p.model_dump()
    w, h = p.width_px, p.height_px
    d["aspect"] = round(w / h, 4) if h else None
    return d


@router.get("")
def list_presets(session: Session = Depends(get_session),
                 _user=Depends(require_role("admin", "organizer"))):
    rows = session.exec(select(OutputPreset).order_by(OutputPreset.kind, OutputPreset.name)).all()
    return {"presets": [_preset_dict(p) for p in rows]}


@router.get("/paper-dimensions")
async def paper_dimensions(paper: str = "", dpi: int = 300, printer: str = ""):
    """Resolve a printer media name to its physical size (mm) and the pixel
    canvas at *dpi*. ``printer`` is accepted for symmetry but the size is
    derived from the media name itself."""
    dpi = max(1, min(1200, int(dpi)))
    mm = await asyncio.to_thread(paper_size_mm, paper)
    if not mm:
        return {"resolved": False, "width_mm": None, "height_mm": None,
                "width_px": None, "height_px": None, "dpi": dpi}
    w_mm, h_mm = mm
    w_px, h_px = px_from_mm(w_mm, h_mm, dpi)
    return {"resolved": True, "width_mm": round(w_mm, 1), "height_mm": round(h_mm, 1),
            "width_px": w_px, "height_px": h_px, "dpi": dpi}


def _apply_orientation(width_px: int, height_px: int, orientation: str) -> tuple[int, int]:
    """Return (w, h) so that landscape => wide, portrait => tall."""
    lo, hi = min(width_px, height_px), max(width_px, height_px)
    return (hi, lo) if orientation == "landscape" else (lo, hi)


@router.post("", status_code=201)
def create_preset(body: dict, session: Session = Depends(get_session),
                  _user=Depends(require_role("admin", "organizer"))):
    p = OutputPreset(name=body.get("name", "Neues Format"),
                     kind=body.get("kind", "print"))
    _assign(p, body)
    session.add(p)
    session.commit()
    session.refresh(p)
    return _preset_dict(p)


@router.put("/{preset_id:int}")
def update_preset(preset_id: int, body: dict, session: Session = Depends(get_session),
                  _user=Depends(require_role("admin", "organizer"))):
    p = session.get(OutputPreset, preset_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Preset not found")
    if p.builtin and body.get("kind", p.kind) != "social":
        raise HTTPException(status_code=400, detail="Built-in Formate können nicht umgewandelt werden")
    _assign(p, body)
    session.add(p)
    session.commit()
    session.refresh(p)
    return _preset_dict(p)


@router.delete("/{preset_id:int}", status_code=204)
def delete_preset(preset_id: int, session: Session = Depends(get_session),
                  _user=Depends(require_role("admin", "organizer"))):
    p = session.get(OutputPreset, preset_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Preset not found")
    if p.builtin:
        raise HTTPException(status_code=400, detail="Built-in Format kann nicht gelöscht werden")
    session.delete(p)
    session.commit()


def _assign(p: OutputPreset, body: dict) -> None:
    """Copy editable fields from *body* onto preset *p*, recomputing print px."""
    if "name" in body:
        p.name = body["name"]
    if "kind" in body and not p.builtin:
        p.kind = body["kind"]

    if p.kind == "print":
        if "dpi" in body:
            p.dpi = max(1, min(1200, int(body["dpi"] or 300)))
        if "printer_name" in body:
            p.printer_name = body["printer_name"] or None
        if "paper_size" in body:
            p.paper_size = body["paper_size"] or None
        if "orientation" in body:
            p.orientation = "landscape" if body["orientation"] == "landscape" else "portrait"
        if "copies" in body:
            p.copies = max(1, int(body["copies"] or 1))
        if "margin_mm" in body:
            p.margin_mm = max(0.0, float(body["margin_mm"] or 0))
        if "fit_to_page" in body:
            p.fit_to_page = bool(body["fit_to_page"])
        # Physical size: explicit mm wins, else resolve from the paper name.
        w_mm = body.get("width_mm")
        h_mm = body.get("height_mm")
        if (w_mm in (None, "", 0)) and p.paper_size:
            resolved = paper_size_mm(p.paper_size)
            if resolved:
                w_mm, h_mm = resolved
        if w_mm and h_mm:
            p.width_mm, p.height_mm = float(w_mm), float(h_mm)
            wpx, hpx = px_from_mm(float(w_mm), float(h_mm), p.dpi)
            p.width_px, p.height_px = _apply_orientation(wpx, hpx, p.orientation)
        elif "width_px" in body and "height_px" in body:
            p.width_px, p.height_px = _apply_orientation(
                int(body["width_px"]), int(body["height_px"]), p.orientation)
    else:  # social — fixed pixels, no printer
        if "width_px" in body:
            p.width_px = max(1, int(body["width_px"]))
        if "height_px" in body:
            p.height_px = max(1, int(body["height_px"]))
        p.printer_name = None
        p.paper_size = None
