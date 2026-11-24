"""per-camera stream health of each device: devices.camera_health

Revision ID: 0016_device_camera_health
Revises: 0015_hot_indices
Create Date: 2026-11-23

An edge with several cameras reports each camera's stream state (ok / reconnecting / down),
last frame time and fps on its retained `online` status (`DeviceStatus.camera_health`).
Ingest keeps the latest list here, next to `devices.cameras`; `GET /api/cameras` reads it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0016_device_camera_health"
down_revision: str | None = "0015_hot_indices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("camera_health", JSONB, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("devices", "camera_health")
