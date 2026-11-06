"""staff suggestion photo: suggestions.snapshot_path

Revision ID: 0011_suggestion_snapshot
Revises: 0010_telegram_links
Create Date: 2026-11-06

The edge already sends a face-blurred person crop on `snapshots/{suggestion_id}` and ingest
already stores it in SNAPSHOT_DIR. The row now remembers it, so the API can link it as the
suggestion's `snapshot_url`. NULL = no crop was sent (older rows stay NULL).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_suggestion_snapshot"
down_revision: str | None = "0010_telegram_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("suggestions", sa.Column("snapshot_path", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("suggestions", "snapshot_path")
