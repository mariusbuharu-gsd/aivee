"""uploaded clips for offline analysis: video_uploads

Revision ID: 0009_video_uploads
Revises: 0008_alert_verification
Create Date: 2026-11-06

One row per uploaded clip. Its alerts are ordinary event rows of a virtual camera
(`video-<id>`) on the upload device; `clip_epoch` is the instant the edge counts clip
positions from, so an alert's position in the clip is `at - clip_epoch`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_video_uploads"
down_revision: str | None = "0008_alert_verification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "video_uploads",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "location_id",
            sa.String(64),
            sa.ForeignKey("sites.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("camera_id", sa.String(64), nullable=False, unique=True),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("source_camera_id", sa.String(64), nullable=True),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("rotate", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Float, nullable=False, server_default="0"),
        sa.Column("duration_s", sa.Float, nullable=True),
        sa.Column("events", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_ro", sa.Text, nullable=True),
        sa.Column(
            "created_by_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_video_uploads_created_by_id"),
            nullable=True,
        ),
        sa.Column("created_by_name", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("clip_epoch", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')", name="video_upload_status"
        ),
        sa.CheckConstraint("rotate IN (0, 90, 180, 270)", name="video_upload_rotate"),
    )


def downgrade() -> None:
    op.drop_table("video_uploads")
