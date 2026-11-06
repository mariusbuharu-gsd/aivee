"""auth and tenancy: organizations, locations, users, sessions, memberships, invites, audit_log

Sites become locations: they gain org_id, type and telegram_chat_id (the table keeps its name,
so code that still writes `sites` keeps working). The existing `demo` site moves into the demo
organization. audit_log is append-only for the role that runs the migration (= the API's role):
UPDATE/DELETE/TRUNCATE are revoked, and a trigger rejects them too, because the dev role owns the
table and may be a superuser (both ignore privileges).

Revision ID: 0003_auth_tenancy
Revises: 0001
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003_auth_tenancy"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEMO_ORG_ID = "org-demo"


def _created() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        _created(),
    )

    op.add_column(
        "sites",
        sa.Column(
            "org_id",
            sa.String(64),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,  # ingest may create a site before anyone claims it
        ),
    )
    op.add_column("sites", sa.Column("type", sa.String(16), nullable=False, server_default="other"))
    op.add_column("sites", sa.Column("telegram_chat_id", sa.Text, nullable=True))
    op.create_index("ix_sites_org_id", "sites", ["org_id"])
    op.create_check_constraint(
        "location_type", "sites", "type IN ('restaurant', 'terrace', 'event', 'shop', 'other')"
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "org_id",
            sa.String(64),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("is_owner", sa.Boolean, nullable=False, server_default=sa.false()),
        _created(),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        _created(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )
    op.create_table(
        "memberships",
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "location_id",
            sa.String(64),
            sa.ForeignKey("sites.id", ondelete="CASCADE"),
            primary_key=True,
            index=True,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        _created(),
        sa.CheckConstraint("role IN ('manager', 'staff')", name="membership_role"),
    )
    op.create_table(
        "invites",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "org_id",
            sa.String(64),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            sa.String(64),
            sa.ForeignKey("sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("invited_by", sa.String(64), sa.ForeignKey("users.id", ondelete="SET NULL")),
        _created(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("role IN ('manager', 'staff')", name="invite_role"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("org_id", sa.String(64), index=True),
        sa.Column("location_id", sa.String(64), index=True),
        sa.Column("actor_kind", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False, index=True),
        sa.Column("actor_name", sa.Text, nullable=False, server_default=""),
        sa.Column("kind", sa.String(64), nullable=False, index=True),
        sa.Column("target_type", sa.String(32)),
        sa.Column("target_id", sa.String(128)),
        sa.Column("target_label", sa.Text),
        sa.Column("summary_ro", sa.Text, nullable=False, server_default=""),
        sa.Column("before", JSONB),
        sa.Column("after", JSONB),
        sa.CheckConstraint("actor_kind IN ('user', 'device', 'system')", name="audit_actor_kind"),
    )
    op.create_index("ix_audit_log_at", "audit_log", ["at"])
    op.execute(
        """
        CREATE FUNCTION audit_log_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only (% rejected)', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION audit_log_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_log_append_only()"
    )
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM PUBLIC")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM CURRENT_USER")

    # The existing demo site becomes the demo organization's location.
    op.execute(
        f"""
        INSERT INTO organizations (id, name)
        SELECT '{DEMO_ORG_ID}', 'AiVee Demo' WHERE EXISTS (SELECT 1 FROM sites WHERE id = 'demo')
        """
    )
    op.execute(
        f"""
        UPDATE sites SET org_id = '{DEMO_ORG_ID}', type = 'restaurant',
            name = CASE WHEN name IN ('', 'demo') THEN 'Terasa demo' ELSE name END
        WHERE id = 'demo'
        """
    )


def downgrade() -> None:
    op.drop_table("audit_log")  # DROP is not blocked by the row/statement triggers
    op.execute("DROP FUNCTION IF EXISTS audit_log_append_only()")
    op.drop_table("invites")
    op.drop_table("memberships")
    op.drop_table("sessions")
    op.drop_table("users")
    op.drop_constraint("location_type", "sites", type_="check")
    op.drop_index("ix_sites_org_id", "sites")
    op.drop_column("sites", "telegram_chat_id")
    op.drop_column("sites", "type")
    op.drop_column("sites", "org_id")
    op.drop_table("organizations")
