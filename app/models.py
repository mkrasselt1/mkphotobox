"""SQLModel ORM models for the photobox database."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    role: str = Field(default="user")  # admin | organizer | user
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = Field(default=True)


class Permission(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    setting_key: str  # dotted path, e.g. "cameras.gphoto2.enabled"
    can_read: bool = Field(default=True)
    can_write: bool = Field(default=False)


class Event(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    slug: str = Field(unique=True, index=True)
    organizer_id: Optional[int] = Field(default=None, foreign_key="user.id")
    config_json: str = Field(default="{}")  # event-specific config overrides
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = Field(default=False)


class PhotoSession(SQLModel, table=True):
    __tablename__ = "photo_session"

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    token: str = Field(unique=True, index=True)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
    payment_id: Optional[int] = Field(default=None, foreign_key="payment.id")


class Photo(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="photo_session.id", index=True)
    filename: str
    gif_filename: Optional[str] = None
    thumbnail: Optional[str] = None
    original_path: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    file_size: Optional[int] = None
    captured_at: datetime = Field(default_factory=datetime.utcnow)
    camera_module: Optional[str] = None
    sequence_index: int = Field(default=0)
    metadata_json: str = Field(default="{}")


class Collage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="photo_session.id", index=True)
    template_id: str
    result_path: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CollagePhoto(SQLModel, table=True):
    __tablename__ = "collage_photo"

    id: Optional[int] = Field(default=None, primary_key=True)
    collage_id: int = Field(foreign_key="collage.id")
    photo_id: int = Field(foreign_key="photo.id")
    slot_index: int


class Payment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    module: str  # stripe_qr | sumup_qr | sumup_terminal | mdb
    amount_cents: int
    paid_cents: int = Field(default=0)  # actually received (relevant for cash/MDB)
    credit_cents: int = Field(default=0)  # overpayment carried as session credit
    currency: str = Field(default="EUR")
    status: str = Field(default="pending")  # pending | completed | failed | refunded
    external_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    metadata_json: str = Field(default="{}")


class OutputJob(SQLModel, table=True):
    __tablename__ = "output_job"

    id: Optional[int] = Field(default=None, primary_key=True)
    photo_id: Optional[int] = Field(default=None, foreign_key="photo.id")
    collage_id: Optional[int] = Field(default=None, foreign_key="collage.id")
    module: str  # email | printer | download | web_upload | ...
    status: str = Field(default="queued")  # queued | processing | completed | failed
    target: Optional[str] = None  # email address, printer name, etc.
    error_msg: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    retry_count: int = Field(default=0)


class SyncQueue(SQLModel, table=True):
    __tablename__ = "sync_queue"

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_type: str
    entity_id: int
    action: str  # create | update | delete
    payload_json: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    synced_at: Optional[datetime] = None


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value_json: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by: Optional[int] = Field(default=None, foreign_key="user.id")


class Asset(SQLModel, table=True):
    """An imported graphic: background, frame/overlay, logo or sticker."""

    id: Optional[int] = Field(default=None, primary_key=True)
    type: str = Field(index=True)  # background | frame | logo | sticker
    name: str
    filename: str  # relative to data/assets/<type>/
    thumbnail: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    source: Optional[str] = None  # original import path/drive
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Template(SQLModel, table=True):
    """A photo layout/frame. Slots are always stored explicitly (canvas px);
    the editor generates them either from a grid preset or via free drag&drop."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    mode: str = Field(default="grid")  # grid | free (informational)
    canvas_width: int = Field(default=1200)
    canvas_height: int = Field(default=1800)
    photo_count: int = Field(default=1)
    # Optional link to an output preset (print paper / social format). When set,
    # the canvas dimensions follow the preset and printing this template's
    # collages routes to the preset's printer + paper.
    preset_id: Optional[int] = Field(default=None, foreign_key="output_preset.id")
    background_asset_id: Optional[int] = Field(default=None, foreign_key="asset.id")
    overlay_asset_id: Optional[int] = Field(default=None, foreign_key="asset.id")
    # definition_json: {"slots": [...], "overlays": [...]}
    definition_json: str = Field(default='{"slots": [], "overlays": []}')
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OutputPreset(SQLModel, table=True):
    """A reusable output format: either a physical print paper (read from the
    printer, so the canvas isn't a pixel guess) or a digital/social format.

    The pixel size drives the template canvas; for print presets the physical
    size (mm) + dpi derive those pixels, and the printer/paper/copies are used
    when a linked template's collage is printed.
    """

    __tablename__ = "output_preset"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    kind: str = Field(default="print")  # print | social
    width_px: int = Field(default=1200)
    height_px: int = Field(default=1800)
    dpi: int = Field(default=300)
    # ── print-specific (None/ignored for social) ──
    printer_name: Optional[str] = None
    paper_size: Optional[str] = None          # CUPS/Windows media name
    width_mm: Optional[float] = None          # physical paper size (short edge)
    height_mm: Optional[float] = None         # physical paper size (long edge)
    orientation: str = Field(default="portrait")  # portrait | landscape
    copies: int = Field(default=1)
    margin_mm: float = Field(default=0)
    fit_to_page: bool = Field(default=True)
    builtin: bool = Field(default=False)      # seeded social formats — not deletable
    created_at: datetime = Field(default_factory=datetime.utcnow)
