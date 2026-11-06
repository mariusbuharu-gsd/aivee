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


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _now()


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
    acknowledged_by_id: Mapped[str | None] = mapped_column(String(64))
    acknowledged_by_name: Mapped[str | None] = mapped_column(Text)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
