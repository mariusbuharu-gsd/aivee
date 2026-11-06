"""alert re-alerted after an unfulfilled acknowledgement: realerted_at

Revision ID: 0007_alert_realerted_at
Revises: 0006_invite_revoked_at
Create Date: 2026-11-06

Set on the opened row when ingest tells the whole shift again that nobody arrived
REALERT_AFTER_S after "Merg eu". NULL = not re-alerted; set at most once per alert.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_alert_realerted_at"
down_revision: str | None = "0006_invite_revoked_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("realerted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "realerted_at")
