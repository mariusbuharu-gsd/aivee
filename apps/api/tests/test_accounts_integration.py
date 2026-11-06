"""Locations, members and invites, scoped by role and organization."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from aivee_api.accounts.models import Invite
from aivee_api.audit.models import AuditRow
from sqlalchemy import select, update

pytestmark = pytest.mark.integration


@pytest.fixture
async def t(sessions: Any, tenancy_factory: Any) -> Any:
    return await tenancy_factory(sessions)


async def _as(client_factory: Any, login: Any, email: str) -> httpx.AsyncClient:
    c: httpx.AsyncClient = client_factory()
    await login(c, email)
    return c


async def _kinds(sessions: Any) -> list[str]:
    async with sessions() as s:
        return list(await s.scalars(select(AuditRow.kind).order_by(AuditRow.id)))


async def test_invite_then_accept_logs_the_new_staff_in(
    t: Any, client_factory: Any, login: Any, sessions: Any
) -> None:
    manager = await _as(client_factory, login, "manager@t.ro")
    r = await manager.post(
        "/api/invites", json={"location_id": "test", "role": "staff", "email": "Ion@T.ro"}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["invite_url"].startswith("http://localhost:5173/invitatie/")
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(days=6, hours=23) < expires - datetime.now(UTC) <= timedelta(days=7)
    token = body["invite_url"].rsplit("/", 1)[1]

    async with client_factory() as guest:
        info = (await guest.get(f"/api/invites/{token}")).json()
        assert info == {
            "org_name": "Org T",
            "location_name": "Terasa",
            "role": "staff",
            "email": "ion@t.ro",
        }
        r = await guest.post(
            f"/api/invites/{token}/accept", json={"name": "Ion", "password": "scurt"}
        )
        assert r.status_code == 422
        r = await guest.post(
            f"/api/invites/{token}/accept", json={"name": "Ion", "password": "parola-ion-1"}
        )
        assert r.status_code == 200, r.text
        me = r.json()
        assert me["user"]["email"] == "ion@t.ro" and me["org"]["id"] == "org-t"
        assert [(x["id"], x["role"]) for x in me["locations"]] == [("test", "staff")]
        assert (await guest.get("/api/auth/me")).status_code == 200  # cookie set

        # the link works once
        assert (await guest.get(f"/api/invites/{token}")).status_code == 404
        r = await guest.post(
            f"/api/invites/{token}/accept", json={"name": "X", "password": "parola-ion-1"}
        )
        assert r.status_code == 404

    members = (await manager.get("/api/locations/test/members")).json()
    assert {(m["email"], m["role"]) for m in members} >= {
        ("ion@t.ro", "staff"),
        ("owner@t.ro", "owner"),
    }
    assert (await _kinds(sessions))[-2:] == ["user.invited", "user.joined"]
    await manager.aclose()


async def test_invite_rules(t: Any, client_factory: Any, login: Any, sessions: Any) -> None:
    manager = await _as(client_factory, login, "manager@t.ro")
    staff = await _as(client_factory, login, "staff@t.ro")
    invite = {"location_id": "test", "role": "manager", "email": "nou@t.ro"}
    assert (await manager.post("/api/invites", json=invite)).status_code == 403  # staff only
    assert (await staff.post("/api/invites", json={**invite, "role": "staff"})).status_code == 403
    other = {**invite, "role": "staff", "location_id": "other"}
    assert (await manager.post("/api/invites", json=other)).status_code == 404
    far = {**invite, "role": "staff", "location_id": "far"}
    assert (await manager.post("/api/invites", json=far)).status_code == 404
    taken = {**invite, "role": "staff", "email": "staff@t.ro"}
    assert (await manager.post("/api/invites", json=taken)).status_code == 409

    r = await manager.post("/api/invites", json={**invite, "role": "staff"})
    token = r.json()["invite_url"].rsplit("/", 1)[1]
    async with sessions() as s:
        await s.execute(update(Invite).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        await s.commit()
    async with client_factory() as guest:
        assert (await guest.get(f"/api/invites/{token}")).status_code == 404
    assert (await client_factory().get("/api/invites/not-a-token")).status_code == 404
    for c in (manager, staff):
        await c.aclose()


async def test_locations_crud_is_owner_only(
    t: Any, client_factory: Any, login: Any, sessions: Any
) -> None:
    owner = await _as(client_factory, login, "owner@t.ro")
    manager = await _as(client_factory, login, "manager@t.ro")
    xowner = await _as(client_factory, login, "owner@x.ro")

    assert [x["id"] for x in (await owner.get("/api/locations")).json()] == ["test", "other"]
    assert [x["id"] for x in (await manager.get("/api/locations")).json()] == ["test"]

    new = {"id": "bar-1", "name": "Bar", "type": "event", "telegram_chat_id": "-100123"}
    assert (await manager.post("/api/locations", json=new)).status_code == 403
    r = await owner.post("/api/locations", json=new)
    assert r.status_code == 201 and r.json() == new
    assert (await owner.post("/api/locations", json=new)).status_code == 409
    assert (await xowner.post("/api/locations", json={**new, "id": "test"})).status_code == 409
    assert (await owner.post("/api/locations", json={**new, "id": "a/b"})).status_code == 422

    assert (await manager.patch("/api/locations/test", json={"name": "X"})).status_code == 403
    assert (await xowner.patch("/api/locations/test", json={"name": "X"})).status_code == 404
    r = await owner.patch(
        "/api/locations/bar-1", json={"name": "Bar nou", "telegram_chat_id": None}
    )
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["telegram_chat_id"], r.json()["type"]) == (
        "Bar nou",
        None,
        "event",
    )
    assert (await xowner.delete("/api/locations/bar-1")).status_code == 404
    assert (await owner.delete("/api/locations/bar-1")).status_code == 204
    assert [x["id"] for x in (await owner.get("/api/locations")).json()] == ["test", "other"]

    async with sessions() as s:
        rows = (
            await s.scalars(
                select(AuditRow).where(AuditRow.kind.startswith("location.")).order_by(AuditRow.id)
            )
        ).all()
    assert [r.kind for r in rows] == ["location.created", "location.updated", "location.deleted"]
    assert rows[1].before["name"] == "Bar" and rows[1].after["name"] == "Bar nou"
    assert rows[1].summary_ro == "Olga a modificat locația Bar nou"
    for c in (owner, manager, xowner):
        await c.aclose()


async def test_members_roles(t: Any, client_factory: Any, login: Any, sessions: Any) -> None:
    owner = await _as(client_factory, login, "owner@t.ro")
    manager = await _as(client_factory, login, "manager@t.ro")
    staff = await _as(client_factory, login, "staff@t.ro")

    assert (await staff.get("/api/locations/test/members")).status_code == 403
    assert (await manager.get("/api/locations/other/members")).status_code == 404
    url = "/api/locations/test/members"
    # manager: staff only
    assert (await manager.patch(f"{url}/u-staff", json={"role": "manager"})).status_code == 403
    assert (await manager.patch(f"{url}/u-manager", json={"role": "staff"})).status_code == 403
    assert (await manager.patch(f"{url}/u-owner", json={"role": "staff"})).status_code == 403
    assert (await manager.patch(f"{url}/u-xowner", json={"role": "staff"})).status_code == 404
    # owner promotes, and can add an org user to another location
    r = await owner.patch(f"{url}/u-staff", json={"role": "manager"})
    assert r.status_code == 200 and r.json()["role"] == "manager"
    r = await owner.patch(f"{url}/u-other", json={"role": "staff"})
    assert r.status_code == 200
    # manager removes staff, not managers
    assert (await manager.delete(f"{url}/u-staff")).status_code == 403
    assert (await manager.delete(f"{url}/u-other")).status_code == 204
    assert (await manager.delete(f"{url}/u-other")).status_code == 404
    assert (await owner.delete(f"{url}/u-staff")).status_code == 204
    me = (await staff.get("/api/auth/me")).json()
    assert me["locations"] == []  # removed: the staff user sees nothing any more

    async with sessions() as s:
        rows = (
            await s.scalars(
                select(AuditRow).where(AuditRow.kind.startswith("member.")).order_by(AuditRow.id)
            )
        ).all()
    assert [r.kind for r in rows] == [
        "member.role_changed",
        "member.role_changed",
        "member.removed",
        "member.removed",
    ]
    assert rows[0].before == {"role": "staff"} and rows[0].after == {"role": "manager"}
    assert rows[0].summary_ro == "Olga a schimbat rolul lui Ana din angajat în manager"
    for c in (owner, manager, staff):
        await c.aclose()
