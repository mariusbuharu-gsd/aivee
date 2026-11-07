"""alert lifecycle messages: the Telegram alert's message, and the last reminder

Revision ID: 0013_alert_messages
Revises: 0012_location_service_target
Create Date: 2026-11-07

Ingest edits the original Telegram alert when the alert resolves (staff arrived, guest
left), so the opened row keeps the chat and message id it went out as. `reminded_at` is
the last "⏰ Încă neservit" reminder (REMIND_S), claimed atomically by one replica.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_alert_messages"
down_revision: str | None = "0012_location_service_target"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("telegram_chat_id", sa.String(64), nullable=True))
    op.add_column("events", sa.Column("telegram_message_id", sa.BigInteger, nullable=True))
    op.add_column("events", sa.Column("telegram_photo", sa.Boolean, nullable=True))
    op.add_column("events", sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "reminded_at")
    op.drop_column("events", "telegram_photo")
    op.drop_column("events", "telegram_message_id")
    op.drop_column("events", "telegram_chat_id")
