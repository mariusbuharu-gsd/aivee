"""alert closed by the system: why (device_offline | device_restarted)

Revision ID: 0005_alert_closed_reason
Revises: 0004_alert_lifecycle
Create Date: 2026-11-06

Set on the opened row when ingest closes an alert because its device went offline or
came back with a fresh engine. NULL with `closed_at` set means the edge closed it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_alert_closed_reason"
down_revision: str | None = "0004_alert_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("closed_reason", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "closed_reason")
