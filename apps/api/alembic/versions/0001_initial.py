"""initial schema: sites, devices, cameras, rules, events, staff, suggestions

Revision ID: 0001
Revises:
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIM = 512


def _created() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "sites",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.Text, nullable=False, server_default=""),
        _created(),
    )
    op.create_table(
        "devices",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "site_id", sa.String(64), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("state", sa.String(16), nullable=False, server_default="offline"),
        sa.Column("version", sa.String(32), nullable=False, server_default=""),
        sa.Column("cameras", JSONB, nullable=False, server_default="[]"),
        sa.Column("last_seen", sa.DateTime(timezone=True)),
        sa.CheckConstraint("state IN ('online', 'offline')", name="device_state"),
    )
    op.create_table(
        "cameras",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("device_id", sa.String(64), sa.ForeignKey("devices.id", ondelete="SET NULL")),
        sa.Column("name", sa.Text, nullable=False, server_default=""),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("zones", JSONB, nullable=False, server_default="[]"),
    )
    op.create_table(
        "rules",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "camera_id",
            sa.String(64),
            sa.ForeignKey("cameras.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule", JSONB, nullable=False),
        sa.Column("prompt_ro", sa.Text, nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        _created(),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(64), nullable=False, unique=True),
        sa.Column("device_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("rule_id", sa.String(64), nullable=False, index=True),
        sa.Column("camera_id", sa.String(64), nullable=False, index=True),
        sa.Column("zone_id", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("summary_ro", sa.Text, nullable=False, server_default=""),
        sa.Column("snapshot_path", sa.Text),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("state IN ('opened', 'closed')", name="event_state"),
    )
    op.create_table(
        "staff_profiles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description_ro", sa.Text, nullable=False, server_default=""),
        sa.Column("centroid", Vector(DIM)),
        _created(),
    )
    op.create_table(
        "staff_examples",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "profile_id",
            sa.String(64),
            sa.ForeignKey("staff_profiles.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("embedding", Vector(DIM), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="upload"),
        _created(),
    )
    op.create_table(
        "suggestions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("suggestion_id", sa.String(64), nullable=False, unique=True),
        sa.Column("device_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("camera_id", sa.String(64), nullable=False),
        sa.Column("track_id", sa.Integer, nullable=False),
        sa.Column("staff_score", sa.Float, nullable=False),
        sa.Column("reason_ro", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        _created(),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'rejected')", name="suggestion_status"
        ),
    )


def downgrade() -> None:
    for table in (
        "suggestions",
        "staff_examples",
        "staff_profiles",
        "events",
        "rules",
        "cameras",
        "devices",
        "sites",
    ):
        op.drop_table(table)
    # The vector extension is left in place: init.sql and other databases may rely on it.
