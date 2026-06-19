"""Printer configuration API endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import require_role
from app.config import get_config, set_nested

router = APIRouter(prefix="/api/v1/printer", tags=["printer"])


@router.get("/list")
async def list_printers():
    """List available printers on the system."""
    from app.modules.output.printer import PrinterOutput
    printers = await asyncio.to_thread(PrinterOutput.list_printers)
    return {"printers": printers}


@router.get("/paper-sizes")
async def list_paper_sizes(printer: str = ""):
    """Return the paper sizes supported by a given printer (CUPS/Windows)."""
    from app.modules.output.printer import PrinterOutput
    return await asyncio.to_thread(PrinterOutput.list_paper_sizes, printer)


@router.get("/status")
def get_printer_status(request: Request):
    """Get current printer configuration."""
    cfg = get_config()
    printer_cfg = cfg.get("outputs", {}).get("printer", {})
    return {
        "enabled": printer_cfg.get("enabled", False),
        "mode": printer_cfg.get("mode", "browser"),
        "printer_name": printer_cfg.get("printer_name", ""),
        "paper_size": printer_cfg.get("paper_size", "4x6"),
        "copies": printer_cfg.get("copies", 1),
        "orientation": printer_cfg.get("orientation", "portrait"),
        "fit_to_page": printer_cfg.get("fit_to_page", True),
        "margin_mm": printer_cfg.get("margin_mm", 0),
    }


@router.post("/configure")
async def configure_printer(
    body: dict,
    request: Request,
    _user=Depends(require_role("admin", "organizer")),
):
    """Update printer settings and (re)load the output module so it's usable."""
    cfg = get_config()

    allowed_keys = ("enabled", "mode", "printer_name", "paper_size", "copies",
                    "orientation", "fit_to_page", "margin_mm")
    for key in allowed_keys:
        if key in body:
            set_nested(cfg, f"outputs.printer.{key}", body[key])

    # (Re)load the printer output so it becomes available even if it was
    # disabled at startup. "browser" mode is always available.
    printer_cfg = cfg.get("outputs", {}).get("printer", {})
    outputs = request.app.state.outputs
    available = await outputs.reload_output("output.printer", printer_cfg)

    return {"status": "ok", "available": available,
            **{k: body[k] for k in allowed_keys if k in body}}


@router.post("/test")
async def test_print(
    request: Request,
    _user=Depends(require_role("admin", "organizer")),
):
    """Send a test print (uses a recent photo or a test pattern)."""
    from sqlmodel import Session, select
    from app.database import get_engine
    from app.models import Photo

    cfg = get_config()
    photo_path = None

    # Find the most recent photo
    engine = get_engine()
    with Session(engine) as session:
        photo = session.exec(select(Photo).order_by(Photo.captured_at.desc())).first()
        if photo:
            photo_path = str(Path(cfg["photos"]["storage_path"]) / photo.filename)

    if not photo_path or not Path(photo_path).exists():
        # Create a simple test pattern
        try:
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new("RGB", (640, 480), "white")
            draw = ImageDraw.Draw(img)
            draw.text((200, 200), "Photobox\nTest Print", fill="black")
            draw.rectangle([20, 20, 620, 460], outline="black", width=3)
            test_path = Path(cfg["photos"]["storage_path"]) / "test_print.jpg"
            test_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(test_path, "JPEG", quality=90)
            photo_path = str(test_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Cannot create test image: {e}")

    outputs = request.app.state.outputs
    result = await outputs.send("output.printer", photo_path, {})
    return result
