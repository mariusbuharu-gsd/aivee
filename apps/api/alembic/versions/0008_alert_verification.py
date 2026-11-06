"""alert verification by a vision model, and the before image of an object change

Revision ID: 0008_alert_verification
Revises: 0007_alert_realerted_at
Create Date: 2026-11-06

On the opened row (one verification per alert): status pending | confirmed | rejected |
unavailable, the model's Romanian summary and object name, which model answered, how
long it took and when. Grouped by rule_id and status they give the false-alarm rate per
rule. `before_snapshot_path` is the "before" JPEG of an object_gone alert.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_alert_verification"
down_revision: str | None = "0007_alert_realerted_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    sa.Column("before_snapshot_path", sa.Text(), nullable=True),
    sa.Column("verification_status", sa.String(16), nullable=True),
    sa.Column("verification_summary_ro", sa.Text(), nullable=True),
    sa.Column("verification_object_ro", sa.Text(), nullable=True),
    sa.Column("verification_model", sa.String(64), nullable=True),
    sa.Column("verification_latency_ms", sa.Integer(), nullable=True),
    sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
)


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column("events", column)
    op.create_index("ix_events_rule_verification", "events", ["rule_id", "verification_status"])


def downgrade() -> None:
    op.drop_index("ix_events_rule_verification", table_name="events")
    for column in reversed(COLUMNS):
        op.drop_column("events", column.name)
