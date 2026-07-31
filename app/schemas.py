"""Pydantic request/response schemas for the API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field


# ── Auth ──────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    role: str
    username: str


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "organizer"


class UserUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


# ── Events ────────────────────────────────────────────────────────────────

class EventLocation(BaseModel):
    """Venue of an event — written into the GPS/EXIF metadata of its files."""

    location_name: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    altitude: Optional[float] = None


class EventCreate(EventLocation):
    name: str
    slug: str
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    config_json: str = "{}"


class EventUpdate(EventLocation):
    name: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    config_json: Optional[str] = None
    is_active: Optional[bool] = None


class EventResponse(EventLocation):
    id: int
    name: str
    slug: str
    organizer_id: Optional[int]
    config_json: str
    starts_at: Optional[datetime]
    ends_at: Optional[datetime]
    created_at: datetime
    is_active: bool


# ── Photos ────────────────────────────────────────────────────────────────

class PhotoResponse(BaseModel):
    id: int
    session_id: int
    filename: str
    gif_filename: Optional[str] = None
    thumbnail: Optional[str]
    width: Optional[int]
    height: Optional[int]
    file_size: Optional[int]
    captured_at: datetime
    camera_module: Optional[str]
    sequence_index: int


# ── Sessions ──────────────────────────────────────────────────────────────

class SessionResponse(BaseModel):
    id: int
    event_id: int
    token: str
    started_at: datetime
    ended_at: Optional[datetime]


# ── Output ────────────────────────────────────────────────────────────────

class OutputSendRequest(BaseModel):
    photo_id: Optional[int] = None
    collage_id: Optional[int] = None
    module: str  # e.g. "output.email"
    target: Optional[str] = None  # e.g. email address


class OutputJobResponse(BaseModel):
    id: int
    module: str
    status: str
    target: Optional[str]
    error_msg: Optional[str]
    created_at: datetime


# ── Payment ───────────────────────────────────────────────────────────────

class PaymentInitRequest(BaseModel):
    module: Optional[str] = None
    amount_cents: Optional[int] = None


class PaymentResponse(BaseModel):
    id: int
    module: str
    amount_cents: int
    currency: str
    status: str
    external_id: Optional[str]
    created_at: datetime


# ── Settings ──────────────────────────────────────────────────────────────

class SettingUpdate(BaseModel):
    key: str
    value: Any


# ── Permissions ───────────────────────────────────────────────────────────

class PermissionSet(BaseModel):
    setting_key: str
    can_read: bool = True
    can_write: bool = False


class PermissionResponse(BaseModel):
    id: int
    user_id: int
    setting_key: str
    can_read: bool
    can_write: bool


# ── System ────────────────────────────────────────────────────────────────

class SystemInfo(BaseModel):
    version: str
    platform: str
    python_version: str
    disk_free_mb: int
    photos_count: int
    uptime_seconds: float


# ── Setup Wizard ──────────────────────────────────────────────────────────

class SetupRequest(BaseModel):
    language: str = "de"
    admin_password: str
    camera: str = "webrtc"
    event_name: str = ""
    event_slug: str = ""
