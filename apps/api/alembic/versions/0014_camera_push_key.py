"""per-camera push key for HTTPS frame ingest: cameras.push_key_hash

Revision ID: 0014_camera_push_key
Revises: 0013_alert_messages
Create Date: 2026-11-23

One shared Basic credential (STREAM_PUBLISH_USER/PASSWORD) could push frames into any
camera of any organisation. A camera can now have its own key (`POST
/api/cameras/{id}/push-key`); only its sha256 is stored. With a key set, frames for that
camera need `Authorization: Bearer <key>` and the shared credential is refused for it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_camera_push_key"
down_revision: str | None = "0013_alert_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("push_key_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("cameras", "push_key_hash")
