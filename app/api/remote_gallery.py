"""Remote gallery sync API — configure + monitor off-box event mirroring."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request

from app.auth import require_role
from app.config import get_config, set_nested
from app.services.remote_gallery import PROTOCOLS, get_remote_gallery

router = APIRouter(prefix="/api/v1/remote-gallery", tags=["remote-gallery"])

_KEYS = ("enabled", "protocol", "host", "port", "username", "password",
         "url", "remote_dir", "key_path", "public_url", "title")
_SECRET = {"password"}


def _public_cfg() -> dict:
    rg = get_config().get("remote_gallery", {}) or {}
    out = {k: rg.get(k) for k in _KEYS if k not in _SECRET}
    out["has_password"] = bool(rg.get("password"))
    return out


@router.get("/status")
def status(_user=Depends(require_role("admin", "organizer"))):
    svc = get_remote_gallery()
    return {"config": _public_cfg(), "state": svc.state, "protocols": list(PROTOCOLS)}


@router.post("/configure")
def configure(body: dict, request: Request,
              _user=Depends(require_role("admin"))):
    cfg = get_config()
    for key in _KEYS:
        if key in body:
            # don't wipe a stored password when the field is left blank
            if key == "password" and body.get(key) in (None, ""):
                continue
            set_nested(cfg, f"remote_gallery.{key}", body[key])
    svc = get_remote_gallery()
    svc.configure(get_config())
    request.app.state.config = get_config()
    return {"status": "ok", "config": _public_cfg(), "state": svc.state}


@router.post("/test")
async def test(_user=Depends(require_role("admin"))):
    svc = get_remote_gallery()
    svc.configure(get_config())
    return await asyncio.to_thread(svc.test_connection)


@router.post("/resync")
async def resync(_user=Depends(require_role("admin"))):
    svc = get_remote_gallery()
    svc.configure(get_config())
    return await svc.resync_all()
