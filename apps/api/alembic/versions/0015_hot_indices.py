"""indices on the hot foreign keys and the open-alert lookups

Revision ID: 0015_hot_indices
Revises: 0014_camera_push_key
Create Date: 2026-11-23

Every location-scoped query goes device -> site (`devices_at`), camera -> device and event ->
device, and ingest finds an event's opened alert by (device, camera, rule, zone, at) and a
device's open alerts on every offline or restart. None of these columns was indexed, so each
was a sequential scan of the whole table, for every tenant.

Plain CREATE INDEX (Alembic runs in a transaction): it blocks writes to each table while
it builds. Fine at today's sizes; on a big `events` table, create them CONCURRENTLY by hand
first (same names) and this migration skips them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_hot_indices"
down_revision: str | None = "0014_camera_push_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLAIN = [
    ("ix_events_device_id", "events", ["device_id"]),
    ("ix_devices_site_id", "devices", ["site_id"]),
    ("ix_cameras_device_id", "cameras", ["device_id"]),
    ("ix_rules_camera_id", "rules", ["camera_id"]),
    ("ix_suggestions_device_id", "suggestions", ["device_id"]),
    ("ix_invites_location_id", "invites", ["location_id"]),
]


def upgrade() -> None:
    for name, table, columns in PLAIN:
        op.create_index(name, table, columns, if_not_exists=True)
    op.create_index(
        "ix_events_opened_lookup",
        "events",
        ["device_id", "camera_id", "rule_id", "zone_id", "at"],
        postgresql_where=sa.text("state = 'opened'"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_events_open_by_device",
        "events",
        ["device_id"],
        postgresql_where=sa.text("state = 'opened' AND closed_at IS NULL"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_events_open_by_device", table_name="events")
    op.drop_index("ix_events_opened_lookup", table_name="events")
    for name, table, _ in reversed(PLAIN):
        op.drop_index(name, table_name=table)
