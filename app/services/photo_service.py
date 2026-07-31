"""Photo capture workflow orchestration.

Connects triggers → payment check → countdown → capture → save → output fanout.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.config import get_config
from app.database import get_engine
from app.eventbus import EventBus
from app.models import Event, Photo, PhotoSession
from app.modules.camera import CameraManager
from app.modules.payment import PaymentManager
from app.services import exif_service
from app.websocket_manager import WSManager

logger = logging.getLogger(__name__)


class PhotoService:
    """Orchestrates the photo capture workflow."""

    def __init__(
        self,
        bus: EventBus,
        cameras: CameraManager,
        payments: PaymentManager,
        ws_manager: WSManager,
    ):
        self.bus = bus
        self.cameras = cameras
        self.payments = payments
        self.ws = ws_manager
        self._capturing = False

        # Listen for triggers
        bus.on("trigger.fired", self._on_trigger)

    async def _on_trigger(self, event: str, data: Any) -> None:
        """Handle a trigger event — start the capture workflow."""
        if self._capturing:
            logger.debug("Ignoring trigger — capture already in progress")
            return

        source = data.get("source", "unknown") if data else "unknown"
        logger.info("Trigger fired from: %s", source)

        cfg = get_config()

        # Check if payment is required
        if cfg.get("payment", {}).get("required_before_capture") and self.payments.is_enabled:
            amount = self.payments.get_price("capture")
            await self.bus.emit("payment.required", {
                "source": source,
                "action": "capture",
                "amount_cents": amount,
            })
            return

        await self.start_capture_flow()

    async def start_capture_flow(self) -> dict[str, Any] | None:
        """Run the full capture flow: countdown → capture → save."""
        if self._capturing:
            return None
        self._capturing = True

        cfg = get_config()
        countdown = cfg.get("session", {}).get("countdown_seconds", 3)

        try:
            # Countdown
            for i in range(countdown, 0, -1):
                await self.ws.broadcast("capture.countdown", {"seconds": i})
                await asyncio.sleep(1)

            # Capture
            await self.bus.emit("capture.started", {"camera": self.cameras.active_id})
            jpeg_bytes = await self.cameras.capture()

            # Save
            result = await self._save_photo(jpeg_bytes, cfg)

            await self.bus.emit("capture.completed", {
                "photo_id": result["photo_id"],
                "filename": result["filename"],
            })

            return result

        except Exception as e:
            logger.exception("Capture flow failed")
            await self.bus.emit("capture.error", {"error": str(e)})
            return None

        finally:
            self._capturing = False

    async def _save_photo(self, jpeg_bytes: bytes, cfg: dict) -> dict[str, Any]:
        """Save photo to disk and database."""
        photo_dir = Path(cfg["photos"]["storage_path"])
        photo_dir.mkdir(parents=True, exist_ok=True)
        thumb_dir = photo_dir / "thumbs"
        thumb_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.utcnow()
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{secrets.token_hex(4)}.jpg"
        filepath = photo_dir / filename

        # Save to database
        engine = get_engine()
        with Session(engine) as session:
            # Get or create active event
            event = session.exec(select(Event).where(Event.is_active == True)).first()
            if event is None:
                event = Event(name="Photobox", slug="default", is_active=True)
                session.add(event)
                session.commit()
                session.refresh(event)

            # Stamp event details, camera info and venue GPS into the EXIF block
            # before the file hits the disk (no re-encode — see exif_service).
            if exif_service.is_enabled(cfg):
                meta = exif_service.meta_for_event(event, cfg, self.cameras)
                jpeg_bytes = await asyncio.to_thread(
                    exif_service.tag_jpeg_bytes, jpeg_bytes, meta, now)

            # Write file in thread
            await asyncio.to_thread(filepath.write_bytes, jpeg_bytes)

            # Generate thumbnail in thread (inherits the source's EXIF)
            thumb_name = await asyncio.to_thread(
                self._make_thumbnail, filepath, thumb_dir, cfg["photos"]["thumbnail_size"]
            )

            # Get image dimensions
            width, height = await asyncio.to_thread(self._get_dimensions, filepath)

            # Find or create photo session
            photo_session = session.exec(
                select(PhotoSession)
                .where(PhotoSession.event_id == event.id, PhotoSession.ended_at == None)
                .order_by(PhotoSession.started_at.desc())
            ).first()
            if photo_session is None:
                photo_session = PhotoSession(event_id=event.id, token=secrets.token_urlsafe(8))
                session.add(photo_session)
                session.commit()
                session.refresh(photo_session)

            photo = Photo(
                session_id=photo_session.id,
                filename=filename,
                thumbnail=f"thumbs/{filepath.stem}_thumb.jpg" if thumb_name else None,
                width=width,
                height=height,
                file_size=len(jpeg_bytes),
                captured_at=now,
                camera_module=self.cameras.active_id,
            )
            session.add(photo)
            session.commit()
            session.refresh(photo)

            return {
                "photo_id": photo.id,
                "filename": filename,
                "session_token": photo_session.token,
            }

    @staticmethod
    def _make_thumbnail(filepath: Path, thumb_dir: Path, size: list[int]) -> str | None:
        try:
            from PIL import Image
            img = Image.open(filepath)
            exif = img.info.get("exif")  # carry the photo's metadata to its thumbnail
            img.thumbnail(tuple(size))
            thumb_name = f"{filepath.stem}_thumb.jpg"
            img.save(thumb_dir / thumb_name, "JPEG", quality=75,
                     **({"exif": exif} if exif else {}))
            img.close()
            return thumb_name
        except Exception:
            logger.debug("Thumbnail generation failed", exc_info=True)
            return None

    @staticmethod
    def _get_dimensions(filepath: Path) -> tuple[int | None, int | None]:
        try:
            from PIL import Image
            img = Image.open(filepath)
            w, h = img.size
            img.close()
            return w, h
        except Exception:
            return None, None
