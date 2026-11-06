"""settable service target per location: sites.service_target_s

Revision ID: 0011_location_service_target
Revises: 0010_telegram_links
Create Date: 2026-11-06

The owner's goal for how long a guest may wait for staff after an alert (Metrici draws it
as the target line). Null: no goal set, the dashboard falls back to the rule's time.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_location_service_target"
down_revision: str | None = "0010_telegram_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sites", sa.Column("service_target_s", sa.Integer, nullable=True))
    op.create_check_constraint(
        "service_target_range", "sites", "service_target_s BETWEEN 1 AND 3600"
    )


def downgrade() -> None:
    op.drop_constraint("service_target_range", "sites", type_="check")
    op.drop_column("sites", "service_target_s")
