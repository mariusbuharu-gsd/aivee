"""GET /api/audit scopes, filters and cursor; the repository only appends."""

from typing import Any

import httpx
import pytest
from aivee_api.audit.repository import Actor, AuditRepository, Target
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration


async def _seed(sessions: Any) -> None:
    """A few entries across locations and actors of org-t, plus one of org-x."""
    olga, mihai, ana = (
        Actor("user", "u-owner", "Olga"),
        Actor("user", "u-manager", "Mihai"),
        Actor("user", "u-staff", "Ana"),
    )
    otilia = Actor("user", "u-other", "Otilia")
    async with sessions() as s:
        repo = AuditRepository(s)
        await repo.append(
            "location.created",
            olga,
            org_id="org-t",
            location_id="other",
            target=Target("location", "other", "Sala mare"),
        )
        await repo.append(
            "rule.created",
            mihai,
            org_id="org-t",
            location_id="test",
            target=Target("rule", "r1", "Masa"),
            after={"id": "r1"},
        )
        await repo.append(
            "rule.updated",
            otilia,
            org_id="org-t",
            location_id="other",
            target=Target("rule", "r2", "Bar"),
            before={"a": 1},
            after={"a": 2},
        )
        await repo.append(
            "alert.acknowledged",
            ana,
            org_id="org-t",
            location_id="test",
            target=Target("alert", "ev1", "Masa 4"),
        )
        await repo.append(
            "device.online",
            Actor("device", "edge-01", "edge-01"),
            org_id="org-t",
            location_id="test",
        )
        await repo.append("auth.login", Actor("user", "u-xowner", "Xenia"), org_id="org-x")
        await s.commit()


async def _ids(c: httpx.AsyncClient, query: str = "") -> list[str]:
    r = await c.get(f"/api/audit{query}")
    assert r.status_code == 200, r.text
    return [i["kind"] for i in r.json()["items"]]


@pytest.fixture
async def seeded(sessions: Any, tenancy_factory: Any) -> None:
    await tenancy_factory(sessions)
    await _seed(sessions)


async def test_scopes_by_role(seeded: None, client_factory: Any, login: Any) -> None:
    async with client_factory() as owner, client_factory() as manager, client_factory() as staff:
        await login(owner, "owner@t.ro")
        await login(manager, "manager@t.ro")
        await login(staff, "staff@t.ro")
        # owner: whole org (newest first; three logins), never org-x
        assert await _ids(owner) == [
            "auth.login",
            "auth.login",
            "auth.login",
            "device.online",
            "alert.acknowledged",
            "rule.updated",
            "rule.created",
            "location.created",
        ]
        # manager of `test`: that location + own actions (own login)
        assert await _ids(manager) == [
            "auth.login",
            "device.online",
            "alert.acknowledged",
            "rule.created",
        ]
        # staff: only their own actions
        assert await _ids(staff) == ["auth.login", "alert.acknowledged"]
        # own logins have no location: they stay visible under the location filter
        assert await _ids(staff, "?location_id=test") == ["auth.login", "alert.acknowledged"]
        assert (await staff.get("/api/audit?location_id=other")).status_code == 404
        assert (await manager.get("/api/audit?location_id=far")).status_code == 404


async def _kinds_by(c: httpx.AsyncClient, query: str) -> list[tuple[str, str]]:
    r = await c.get(f"/api/audit{query}")
    assert r.status_code == 200, r.text
    return [(i["kind"], i["actor"]["id"]) for i in r.json()["items"]]


async def test_location_filter_includes_location_less_entries_by_role(
    seeded: None, sessions: Any, client_factory: Any, login: Any
) -> None:
    """auth.* entries have no location. With `location_id` (what the dashboard always
    sends): owner → every one of the org; manager → those of the location's members;
    staff → their own. Never another org's."""
    async with sessions() as s:
        repo = AuditRepository(s)
        await repo.append("auth.logout", Actor("user", "u-staff", "Ana"), org_id="org-t")
        await repo.append("auth.login", Actor("user", "u-other", "Otilia"), org_id="org-t")
        await repo.append(
            "auth.login_failed",
            Actor("user", "u-manager", "Mihai"),
            org_id="org-t",
            target=Target("email", "manager@t.ro", "manager@t.ro"),
        )
        await repo.append("auth.logout", Actor("user", "u-xowner", "Xenia"), org_id="org-x")
        await s.commit()
    async with (
        client_factory() as owner,
        client_factory() as manager,
        client_factory() as staff,
        client_factory() as other,
    ):
        for client, email in (
            (owner, "owner@t.ro"),
            (manager, "manager@t.ro"),
            (staff, "staff@t.ro"),
            (other, "other@t.ro"),
        ):
            await login(client, email)

        assert await _kinds_by(owner, "?location_id=test") == [
            ("auth.login", "u-other"),
            ("auth.login", "u-staff"),
            ("auth.login", "u-manager"),
            ("auth.login", "u-owner"),
            ("auth.login_failed", "u-manager"),
            ("auth.login", "u-other"),
            ("auth.logout", "u-staff"),
            ("device.online", "edge-01"),
            ("alert.acknowledged", "u-staff"),
            ("rule.created", "u-manager"),
        ]
        # members of `test` are Mihai and Ana: not the owner's nor Otilia's logins
        assert await _kinds_by(manager, "?location_id=test") == [
            ("auth.login", "u-staff"),
            ("auth.login", "u-manager"),
            ("auth.login_failed", "u-manager"),
            ("auth.logout", "u-staff"),
            ("device.online", "edge-01"),
            ("alert.acknowledged", "u-staff"),
            ("rule.created", "u-manager"),
        ]
        assert await _kinds_by(manager, "?location_id=test&kind=auth.login") == [
            ("auth.login", "u-staff"),
            ("auth.login", "u-manager"),
        ]
        assert await _kinds_by(staff, "?location_id=test") == [
            ("auth.login", "u-staff"),
            ("auth.logout", "u-staff"),
            ("alert.acknowledged", "u-staff"),
        ]
        assert await _kinds_by(other, "?location_id=other") == [
            ("auth.login", "u-other"),
            ("auth.login", "u-other"),
            ("rule.updated", "u-other"),
            ("location.created", "u-owner"),
        ]
        for client in (manager, staff):
            assert (await client.get("/api/audit?location_id=other")).status_code == 404
        assert (await owner.get("/api/audit?location_id=far")).status_code == 404


async def test_filters_and_cursor(seeded: None, client_factory: Any, login: Any) -> None:
    async with client_factory() as owner:
        await login(owner, "owner@t.ro")
        assert await _ids(owner, "?location_id=other") == [
            "auth.login",  # the owner's own, location-less
            "rule.updated",
            "location.created",
        ]
        assert await _ids(owner, "?actor=u-manager") == ["rule.created"]
        assert await _ids(owner, "?kind=auth") == ["auth.login"]
        assert await _ids(owner, "?kind=rule") == ["rule.updated", "rule.created"]
        assert await _ids(owner, "?kind=rule.created") == ["rule.created"]

        page1 = (await owner.get("/api/audit?limit=4")).json()
        assert len(page1["items"]) == 4 and page1["next_before"] == page1["items"][-1]["id"]
        page2 = (await owner.get(f"/api/audit?limit=4&before={page1['next_before']}")).json()
        assert [i["kind"] for i in page2["items"]] == ["rule.created", "location.created"]
        assert page2["next_before"] is None
        assert (await owner.get("/api/audit?before=abc")).status_code == 422

        [entry] = (await owner.get("/api/audit?kind=rule.updated")).json()["items"]
        assert entry["actor"] == {"kind": "user", "id": "u-other", "name": "Otilia"}
        assert entry["target"] == {"type": "rule", "id": "r2", "label": "Bar"}
        assert (entry["before"], entry["after"]) == ({"a": 1}, {"a": 2})
        assert entry["summary_ro"] == "Otilia a modificat regula „Bar”"
        assert entry["location_id"] == "other" and isinstance(entry["id"], str)


async def test_audit_requires_login(api: httpx.AsyncClient) -> None:
    r = await api.get("/api/audit")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "unauthenticated"


async def test_rows_cannot_be_rewritten_through_the_api_role(sessions: Any) -> None:
    async with sessions() as s:
        await AuditRepository(s).append("auth.login", Actor("user", "u", "U"), org_id=None)
        await s.commit()
    async with sessions() as s:
        with pytest.raises(DBAPIError, match=r"append-only|permission denied"):
            await s.execute(text("UPDATE audit_log SET summary_ro = 'altceva'"))
    assert not hasattr(AuditRepository, "update") and not hasattr(AuditRepository, "delete")
