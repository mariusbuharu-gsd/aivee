"""alert lifecycle: arrived events, acknowledgement and folded times on the opened row

Revision ID: 0004_alert_lifecycle
Revises: 0003_auth_tenancy
Create Date: 2026-11-06

The opened event's row carries the folded alert: `acknowledged_*` (written by the API),
`arrived_at` / `closed_at` (copied by ingest from the later events). Every event row points
at its alert's opened event through `alert_id`.

`acknowledged_by_id` references users.id (ON DELETE SET NULL); the name stays on the row.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_alert_lifecycle"
down_revision: str | None = "0003_auth_tenancy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("event_state", "events", type_="check")
    op.create_check_constraint("event_state", "events", "state IN ('opened', 'arrived', 'closed')")
    op.add_column("events", sa.Column("alert_id", sa.String(64), nullable=True))
    op.add_column("events", sa.Column("acknowledged_at", sa.DateTime(timezone=True)))
    op.add_column("events", sa.Column("acknowledged_by_id", sa.String(64)))
    op.add_column("events", sa.Column("acknowledged_by_name", sa.Text()))
    op.add_column("events", sa.Column("arrived_at", sa.DateTime(timezone=True)))
    op.add_column("events", sa.Column("closed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_events_alert_id", "events", ["alert_id"])
    op.create_index("ix_events_acknowledged_at", "events", ["acknowledged_at"])
    op.create_foreign_key(
        "fk_events_acknowledged_by_id",
        "events",
        "users",
        ["acknowledged_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Existing rows: every opened row is its own alert; fold the closed rows the way the
    # dashboard did (the next closed event of the same camera, rule and zone).
    op.execute("UPDATE events SET alert_id = event_id WHERE state = 'opened'")
    op.execute(
        """
        UPDATE events o SET closed_at = c.at
        FROM events c
        WHERE o.state = 'opened' AND c.state = 'closed'
          AND c.camera_id = o.camera_id AND c.rule_id = o.rule_id AND c.zone_id = o.zone_id
          AND c.at >= o.at
          AND c.at = (
            SELECT min(c2.at) FROM events c2
            WHERE c2.state = 'closed' AND c2.camera_id = o.camera_id
              AND c2.rule_id = o.rule_id AND c2.zone_id = o.zone_id AND c2.at >= o.at
          )
          AND NOT EXISTS (
            SELECT 1 FROM events o2
            WHERE o2.state = 'opened' AND o2.camera_id = o.camera_id
              AND o2.rule_id = o.rule_id AND o2.zone_id = o.zone_id
              AND o2.at > o.at AND o2.at <= c.at
          )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM events WHERE state = 'arrived'")
    op.drop_constraint("fk_events_acknowledged_by_id", "events", type_="foreignkey")
    op.drop_index("ix_events_acknowledged_at", "events")
    op.drop_index("ix_events_alert_id", "events")
    for column in (
        "closed_at",
        "arrived_at",
        "acknowledged_by_name",
        "acknowledged_by_id",
        "acknowledged_at",
        "alert_id",
    ):
        op.drop_column("events", column)
    op.drop_constraint("event_state", "events", type_="check")
    op.create_check_constraint("event_state", "events", "state IN ('opened', 'closed')")
