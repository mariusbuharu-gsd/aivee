"""one-click Telegram connection: telegram_links, sites.telegram_chat_title

Revision ID: 0010_telegram_links
Revises: 0009_video_uploads
Create Date: 2026-11-06

"Conectează Telegram" hands out a deep link with a short single-use code; the bot (in
ingest) resolves it and saves the chat on the location. Only the code's sha256 is stored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_telegram_links"
down_revision: str | None = "0009_video_uploads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sites", sa.Column("telegram_chat_title", sa.Text, nullable=True))
    op.create_table(
        "telegram_links",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "location_id",
            sa.String(64),
            sa.ForeignKey("sites.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_by_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_telegram_links_created_by_id"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chat_id", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("telegram_links")
    op.drop_column("sites", "telegram_chat_title")
