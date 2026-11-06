"""The append-only audit history (D22). No foreign keys: history outlives what it describes,
and a cascading delete would hit the table's no-DELETE trigger."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aivee_api.db.models import Base


class AuditRow(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    org_id: Mapped[str | None] = mapped_column(String(64), index=True)
    location_id: Mapped[str | None] = mapped_column(String(64), index=True)
    actor_kind: Mapped[str] = mapped_column(String(16))  # user | device | system
    actor_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_name: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(128))
    target_label: Mapped[str | None] = mapped_column(Text)
    summary_ro: Mapped[str] = mapped_column(Text, default="")
    before: Mapped[Any | None] = mapped_column(JSONB)
    after: Mapped[Any | None] = mapped_column(JSONB)
