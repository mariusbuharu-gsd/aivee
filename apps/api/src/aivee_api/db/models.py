"""SQLAlchemy 2 models. Ids coming from the edge (device, camera, rule) are text."""

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 512


class Base(DeclarativeBase):
    pass


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


LOCATION_TYPES = ("restaurant", "terrace", "event", "shop", "other")


class Site(Base):
    """A location (D19): the MQTT `<site>` segment. Rows ingest creates for an unknown site
    have no organization and are visible to nobody until an owner claims them."""

    __tablename__ = "sites"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _now()
    org_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(16), default="other", server_default="other")
    telegram_chat_id: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "type IN ('restaurant', 'terrace', 'event', 'shop', 'other')", name="location_type"
        ),
    )


Location = Site


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    state: Mapped[str] = mapped_column(String(16), default="offline")
    version: Mapped[str] = mapped_column(String(32), default="")
    cameras: Mapped[list[str]] = mapped_column(JSONB, default=list)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("state IN ('online', 'offline')", name="device_state"),)


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(Text)
    zones: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class RuleRow(Base):
    __tablename__ = "rules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    rule: Mapped[dict[str, Any]] = mapped_column(JSONB)
    prompt_ro: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = _now()


class EventRow(Base):
    """One AlertEvent. No FKs on rule/camera: ingest must never drop an event."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True)
    device_id: Mapped[str] = mapped_column(String(64), default="")
    rule_id: Mapped[str] = mapped_column(String(64), index=True)
    camera_id: Mapped[str] = mapped_column(String(64), index=True)
    zone_id: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    summary_ro: Mapped[str] = mapped_column(Text, default="")
    snapshot_path: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = _now()
    # Alert lifecycle (aivee_api.alerts): every row points at its alert's opened event;
    # the opened row carries the folded times and who acknowledged it.
    alert_id: Mapped[str | None] = mapped_column(String(64), index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    acknowledged_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_events_acknowledged_by_id")
    )
    acknowledged_by_name: Mapped[str | None] = mapped_column(Text)
    # Set once when the shift is told again that nobody arrived after the ack (ingest).
    realerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when the system (not the edge) closed it: device_offline | device_restarted |
    # camera_deleted | video_end.
    closed_reason: Mapped[str | None] = mapped_column(String(32))
    # The "before" JPEG of an object_gone alert (the snapshot is the "after").
    before_snapshot_path: Mapped[str | None] = mapped_column(Text)
    # A vision model's second opinion, once per alert (ingest): pending | confirmed |
    # rejected | unavailable. By rule_id and status: the false-alarm rate per rule.
    verification_status: Mapped[str | None] = mapped_column(String(16))
    verification_summary_ro: Mapped[str | None] = mapped_column(Text)
    verification_object_ro: Mapped[str | None] = mapped_column(Text)
    verification_model: Mapped[str | None] = mapped_column(String(64))
    verification_latency_ms: Mapped[int | None] = mapped_column(Integer)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("state IN ('opened', 'arrived', 'closed')", name="event_state"),
    )


class StaffProfileRow(Base):
    __tablename__ = "staff_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    description_ro: Mapped[str] = mapped_column(Text, default="")
    centroid: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    created_at: Mapped[datetime] = _now()


class StaffExample(Base):
    __tablename__ = "staff_examples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("staff_profiles.id", ondelete="CASCADE"), index=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    source: Mapped[str] = mapped_column(String(32), default="upload")
    created_at: Mapped[datetime] = _now()


class SuggestionRow(Base):
    __tablename__ = "suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    suggestion_id: Mapped[str] = mapped_column(String(64), unique=True)
    device_id: Mapped[str] = mapped_column(String(64), default="")
    camera_id: Mapped[str] = mapped_column(String(64))
    track_id: Mapped[int] = mapped_column(Integer)
    staff_score: Mapped[float] = mapped_column(Float)
    reason_ro: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'confirmed', 'rejected')", name="suggestion_status"),
    )


class PushSubscriptionRow(Base):
    """A browser's Web Push subscription (the PWA on a waiter's phone). One row per endpoint."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    user_agent: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _now()
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    """The logged-in user who subscribed (0003_auth_tenancy); alerts go to members only."""


VIDEO_STATUSES = ("queued", "running", "done", "failed")


class VideoUploadRow(Base):
    """A recorded clip uploaded for analysis (aivee_api.videos). Its alerts are ordinary
    event rows of the virtual camera `camera_id` (`video-<id>`) on the upload device; the
    clip position of an alert is `at - clip_epoch`."""

    __tablename__ = "video_uploads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    location_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    camera_id: Mapped[str] = mapped_column(String(64), unique=True)
    device_id: Mapped[str] = mapped_column(String(64))
    source_camera_id: Mapped[str | None] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    rotate: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    duration_s: Mapped[float | None] = mapped_column(Float)
    events: Mapped[int] = mapped_column(Integer, default=0)
    error_ro: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_video_uploads_created_by_id")
    )
    created_by_name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    clip_epoch: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """The instant the edge counts clip positions from (set when the run starts)."""
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')", name="video_upload_status"
        ),
        CheckConstraint("rotate IN (0, 90, 180, 270)", name="video_upload_rotate"),
    )
