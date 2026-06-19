"""FastAPI application factory with lifespan management."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from app.config import load_config
from app.database import create_db, get_engine
from app.eventbus import EventBus
from app.i18n import load_translations
from app.modules.camera import CameraManager
from app.modules.output import OutputManager
from app.modules.payment import PaymentManager
from app.modules.trigger import TriggerManager
from app.websocket_manager import WSManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    cfg = load_config()
    app.state.config = cfg

    # Initialize database
    create_db()

    # Ensure default admin user and event exist
    from app.auth import ensure_default_admin
    from app.models import Event
    engine = get_engine()
    with Session(engine) as session:
        ensure_default_admin(session)

        # Ensure at least one active event exists
        from sqlmodel import select
        active_event = session.exec(select(Event).where(Event.is_active == True)).first()
        if active_event is None:
            any_event = session.exec(select(Event)).first()
            if any_event is None:
                event = Event(name="Photobox", slug="default", is_active=True)
                session.add(event)
                session.commit()
                logger.info("Created default event 'Photobox'")
            else:
                any_event.is_active = True
                session.add(any_event)
                session.commit()
                logger.info("Activated existing event: %s", any_event.name)

    # Load translations
    load_translations()

    # Initialize core services
    bus = EventBus()
    ws_manager = WSManager()
    app.state.bus = bus
    app.state.ws_manager = ws_manager

    # Wire event bus to WebSocket broadcast
    async def _broadcast_event(event: str, data):
        await ws_manager.broadcast(event, data)

    bus.on("capture.started", _broadcast_event)
    bus.on("capture.completed", _broadcast_event)
    bus.on("capture.error", _broadcast_event)
    bus.on("trigger.fired", _broadcast_event)
    bus.on("payment.initiated", _broadcast_event)
    bus.on("payment.completed", _broadcast_event)
    bus.on("payment.progress", _broadcast_event)
    bus.on("payment.required", _broadcast_event)
    bus.on("output.started", _broadcast_event)
    bus.on("output.completed", _broadcast_event)
    bus.on("cd_burn.progress", _broadcast_event)
    bus.on("cd_burn.completed", _broadcast_event)
    bus.on("usb_export.progress", _broadcast_event)
    bus.on("usb_export.completed", _broadcast_event)

    # Load modules
    cameras = CameraManager()
    triggers = TriggerManager()
    outputs = OutputManager()
    payments = PaymentManager()

    await cameras.load_configured(cfg)
    await triggers.load_configured(cfg, callback=bus.emit)
    await outputs.load_configured(cfg)
    await payments.load_configured(cfg)
    payments.set_bus(bus)

    app.state.cameras = cameras
    app.state.triggers = triggers
    app.state.outputs = outputs
    app.state.payments = payments

    # GIF service (buffers preview frames)
    from app.services.gif_service import GifService
    gif_service = GifService()
    gif_service.configure(cfg)
    await gif_service.start_buffering(cameras)
    app.state.gif_service = gif_service

    # Photo service (orchestrates capture workflow)
    from app.services.photo_service import PhotoService
    photo_service = PhotoService(bus, cameras, payments, ws_manager)
    app.state.photo_service = photo_service

    logger.info("Photobox started — cameras=%d, triggers=%d, outputs=%d",
                len(cameras.list_cameras()),
                len(triggers.list_triggers()),
                len(outputs.list_outputs()))

    yield

    # Shutdown
    logger.info("Shutting down...")
    await gif_service.stop_buffering()
    await cameras.shutdown_all()
    await triggers.shutdown_all()
    await outputs.shutdown_all()
    await payments.shutdown_all()
    bus.clear()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="MKPhotobox",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routes
    from app.api import assets, auth, background, cd_burn, events, modules, photos, printer, settings, setup, system, templates, tests, triggers, usb_export, wifi, ws

    app.include_router(auth.router)
    app.include_router(auth.user_router)
    app.include_router(assets.router)
    app.include_router(background.router)
    app.include_router(cd_burn.router)
    app.include_router(events.router)
    app.include_router(photos.router)
    app.include_router(printer.router)
    app.include_router(settings.router)
    app.include_router(system.router)
    app.include_router(modules.router)
    app.include_router(setup.router)
    app.include_router(templates.router)
    app.include_router(tests.router)
    app.include_router(triggers.router)
    app.include_router(usb_export.router)
    app.include_router(wifi.router)
    app.include_router(ws.router)

    # Serve frontend static files on a sub-path so it doesn't interfere with API routes
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount("/src", StaticFiles(directory=str(frontend_dir / "src")), name="frontend-src")
        app.mount("/assets", StaticFiles(directory=str(frontend_dir / "assets")), name="frontend-assets")
        vendor_dir = frontend_dir / "vendor"
        if vendor_dir.exists():
            app.mount("/vendor", StaticFiles(directory=str(vendor_dir)), name="frontend-vendor")

        # Serve index.html for all non-API, non-static routes (SPA fallback)
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import HTMLResponse as StarletteHTML

        @app.middleware("http")
        async def spa_fallback(request: StarletteRequest, call_next):
            response = await call_next(request)
            path = request.url.path
            # If a non-API path returns 404, serve index.html (SPA routing)
            if response.status_code == 404 and not path.startswith("/api/"):
                index = frontend_dir / "index.html"
                if index.exists():
                    return StarletteHTML(index.read_text(encoding="utf-8"))
            return response

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    cfg = load_config()
    uvicorn.run(
        "app.main:app",
        host=cfg["server"]["host"],
        port=cfg["server"]["port"],
        workers=cfg["server"]["workers"],
        reload=False,
    )
