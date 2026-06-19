"""Asset import & management: backgrounds, frames, logos, stickers.

Browses the local data store or a removable drive for image files, copies the
chosen ones onto the photobox (``data/assets/<type>/``) and registers them in
the DB with a thumbnail. Browsing is restricted to allowed roots (the import
folder and mounted removable drives) to prevent arbitrary filesystem access.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from sqlmodel import Session, select

from app.config import get_config
from app.database import get_engine
from app.models import Asset
from app.services.usb_export_service import list_drives

logger = logging.getLogger(__name__)

ASSET_TYPES = ("background", "frame", "logo", "sticker")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def _assets_root() -> Path:
    return Path(get_config()["photos"]["storage_path"]).parent / "assets"


def _imports_root() -> Path:
    root = Path(get_config()["photos"]["storage_path"]).parent / "imports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def allowed_roots() -> list[Path]:
    """Directories the user may browse: the import folder + removable drives."""
    roots = [_imports_root().resolve()]
    for d in list_drives():
        try:
            roots.append(Path(d["mountpoint"]).resolve())
        except Exception:
            pass
    return roots


def list_sources() -> list[dict[str, Any]]:
    sources = [{"id": "imports", "label": "Datenspeicher (imports)",
                "path": str(_imports_root().resolve()), "type": "local"}]
    for d in list_drives():
        sources.append({
            "id": d["mountpoint"], "label": f"{d['label']} ({d['mountpoint']})",
            "path": d["mountpoint"], "type": "removable",
        })
    return sources


def _is_allowed(path: Path) -> bool:
    rp = path.resolve()
    for root in allowed_roots():
        try:
            rp.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def browse(path: str) -> dict[str, Any]:
    """List subdirectories and image files inside *path* (must be allowed)."""
    target = Path(path).resolve()
    if not _is_allowed(target):
        raise PermissionError("Pfad ist nicht erlaubt.")
    if not target.is_dir():
        raise FileNotFoundError("Verzeichnis nicht gefunden.")

    dirs, files = [], []
    try:
        for entry in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                dirs.append({"name": entry.name, "path": str(entry.resolve())})
            elif entry.suffix.lower() in IMAGE_EXTS:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = None
                files.append({"name": entry.name, "path": str(entry.resolve()),
                              "size_bytes": size})
    except PermissionError:
        raise PermissionError("Kein Zugriff auf dieses Verzeichnis.")

    parent = target.parent
    return {
        "path": str(target),
        "parent": str(parent) if _is_allowed(parent) and parent != target else None,
        "dirs": dirs,
        "files": files,
    }


def _unique_path(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    i = 1
    while True:
        candidate = directory / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def _make_thumbnail(src: Path, thumb_path: Path) -> None:
    from PIL import Image
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as img:
        img = img.convert("RGBA")
        img.thumbnail((320, 320))
        # Flatten onto checkerboard-free white for the JPEG thumb
        bg = Image.new("RGB", img.size, (240, 240, 240))
        bg.paste(img, mask=img.split()[-1])
        bg.save(thumb_path, "JPEG", quality=80)


def import_files(asset_type: str, file_paths: list[str]) -> list[dict[str, Any]]:
    """Copy selected files into the asset store and register them."""
    if asset_type not in ASSET_TYPES:
        raise ValueError(f"Ungültiger Asset-Typ: {asset_type}")

    from PIL import Image

    dest_dir = _assets_root() / asset_type
    thumb_dir = dest_dir / "thumbs"
    created: list[dict[str, Any]] = []
    engine = get_engine()

    with Session(engine) as session:
        for src_str in file_paths:
            src = Path(src_str)
            if not _is_allowed(src) or not src.is_file():
                logger.warning("Skipping disallowed/missing asset: %s", src_str)
                continue
            if src.suffix.lower() not in IMAGE_EXTS:
                continue

            dest = _unique_path(dest_dir, src.name)
            shutil.copy2(src, dest)

            width = height = None
            try:
                with Image.open(dest) as img:
                    width, height = img.size
            except Exception:
                logger.warning("Could not read image dimensions: %s", dest)

            thumb_name = f"{dest.stem}.jpg"
            thumb_rel = None
            try:
                _make_thumbnail(dest, thumb_dir / thumb_name)
                thumb_rel = f"{asset_type}/thumbs/{thumb_name}"
            except Exception:
                logger.exception("Thumbnail failed for %s", dest)

            asset = Asset(
                type=asset_type,
                name=dest.stem,
                filename=f"{asset_type}/{dest.name}",
                thumbnail=thumb_rel,
                width=width, height=height,
                source=str(src),
            )
            session.add(asset)
            session.commit()
            session.refresh(asset)
            created.append(asset.model_dump())

    return created


def list_assets(asset_type: Optional[str] = None) -> list[dict[str, Any]]:
    engine = get_engine()
    with Session(engine) as session:
        query = select(Asset)
        if asset_type:
            query = query.where(Asset.type == asset_type)
        return [a.model_dump() for a in session.exec(query.order_by(Asset.created_at.desc())).all()]


def get_asset_file(asset_id: int, thumb: bool = False) -> Optional[Path]:
    engine = get_engine()
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        if asset is None:
            return None
        rel = asset.thumbnail if (thumb and asset.thumbnail) else asset.filename
        path = _assets_root() / rel
        return path if path.exists() else None


def delete_asset(asset_id: int) -> bool:
    engine = get_engine()
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        if asset is None:
            return False
        for rel in (asset.filename, asset.thumbnail):
            if rel:
                f = _assets_root() / rel
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    pass
        session.delete(asset)
        session.commit()
        return True
