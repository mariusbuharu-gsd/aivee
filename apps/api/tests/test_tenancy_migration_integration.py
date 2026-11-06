"""0003_auth_tenancy: the demo site moves into the demo org; audit_log is append-only."""

import asyncio

import pytest
from aivee_api.db.migrate import downgrade, upgrade
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration

REV = "0003_auth_tenancy"
NEW_TABLES = {"organizations", "users", "sessions", "memberships", "invites", "audit_log"}


async def _sql(url: str, *statements: str) -> list[list[tuple[object, ...]]]:
    engine = create_async_engine(url)
    out: list[list[tuple[object, ...]]] = []
    try:
        async with engine.begin() as conn:
            for st in statements:
                result = await conn.execute(text(st))
                out.append([tuple(r) for r in result] if result.returns_rows else [])
    finally:
        await engine.dispose()
    return out


def test_upgrade_moves_demo_into_the_demo_org_and_downgrade_reverts(empty_db_url: str) -> None:
    upgrade(empty_db_url, "0001")
    asyncio.run(
        _sql(
            empty_db_url,
            "INSERT INTO sites (id, name) VALUES ('demo', 'demo'), ('other', 'Alta')",
        )
    )
    upgrade(empty_db_url, REV)
    [sites, orgs] = asyncio.run(
        _sql(
            empty_db_url,
            "SELECT id, name, type, org_id FROM sites ORDER BY id",
            "SELECT id, name FROM organizations",
        )
    )
    assert sites == [
        ("demo", "Terasa demo", "restaurant", "org-demo"),
        ("other", "Alta", "other", None),  # unclaimed: visible to nobody
    ]
    assert orgs == [("org-demo", "AiVee Demo")]

    downgrade(empty_db_url, "0001")
    [tables, cols] = asyncio.run(
        _sql(
            empty_db_url,
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'",
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'sites'",
        )
    )
    assert not NEW_TABLES & {t[0] for t in tables}
    assert {c[0] for c in cols} == {"id", "name", "created_at"}
    assert asyncio.run(_sql(empty_db_url, "SELECT id FROM sites ORDER BY id"))[0] == [
        ("demo",),
        ("other",),
    ]


def test_upgrade_on_an_empty_database_creates_no_org(empty_db_url: str) -> None:
    upgrade(empty_db_url, REV)
    assert asyncio.run(_sql(empty_db_url, "SELECT count(*) FROM organizations"))[0] == [(0,)]


AUDIT_ROW = (
    "INSERT INTO audit_log (actor_kind, actor_id, kind, summary_ro) "
    "VALUES ('system', 'x', 'auth.login', 'test')"
)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET summary_ro = 'rescris'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
    ],
)
def test_audit_log_rejects_changes(empty_db_url: str, statement: str) -> None:
    upgrade(empty_db_url, REV)
    asyncio.run(_sql(empty_db_url, AUDIT_ROW))
    with pytest.raises(DBAPIError, match=r"append-only|permission denied"):
        asyncio.run(_sql(empty_db_url, statement))
    assert asyncio.run(_sql(empty_db_url, "SELECT summary_ro FROM audit_log"))[0] == [("test",)]
