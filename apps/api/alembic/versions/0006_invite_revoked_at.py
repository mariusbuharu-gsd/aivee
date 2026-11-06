"""invites can be revoked: revoked_at

Revision ID: 0006_invite_revoked_at
Revises: 0005_alert_closed_reason
Create Date: 2026-11-06

A revoked invite stays in the table (the history points at it); accepting it gives 410.
Pending = not accepted, not revoked, not expired.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_invite_revoked_at"
down_revision: str | None = "0005_alert_closed_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("invites", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("invites", "revoked_at")
