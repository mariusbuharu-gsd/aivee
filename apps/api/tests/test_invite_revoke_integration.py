"""Pending invites: GET /api/invites lists them, DELETE /api/invites/{id} revokes one."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from aivee_api.accounts.models import Invite
from aivee_api.audit.models import AuditRow
from sqlalchemy import select, update

pytestmark = pytest.mark.integration

FIELDS = {"id", "email", "role", "location_id", "created_by", "created_at", "expires_at"}


@pytest.fixture
async def t(sessions: Any, tenancy_factory: Any) -> Any:
    return await tenancy_factory(sessions)


async def _as(client_factory: Any, login: Any, email: str) -> httpx.AsyncClient:
    c: httpx.AsyncClient = client_factory()
    await login(c, email)
    return c


async def _invite(c: httpx.AsyncClient, email: str, role: str, location: str = "test") -> str:
    r = await c.post("/api/invites", json={"location_id": location, "role": role, "email": email})
    assert r.status_code == 201, r.text
    token: str = r.json()["invite_url"].rsplit("/", 1)[1]
    return token


async def _id(sessions: Any, email: str) -> str:
    async with sessions() as s:
        invite_id: str = await s.scalar(select(Invite.id).where(Invite.email == email))
        return invite_id


async def test_pending_invites_by_role(
    t: Any, client_factory: Any, login: Any, sessions: Any
) -> None:
    owner = await _as(client_factory, login, "owner@t.ro")
    manager = await _as(client_factory, login, "manager@t.ro")
    staff = await _as(client_factory, login, "staff@t.ro")
    other = await _as(client_factory, login, "other@t.ro")
    xowner = await _as(client_factory, login, "owner@x.ro")
    await _invite(owner, "sef@t.ro", "manager")
    await _invite(manager, "ion@t.ro", "staff")
    await _invite(owner, "sala@t.ro", "staff", "other")
    accepted = await _invite(manager, "gata@t.ro", "staff")
    await _invite(manager, "vechi@t.ro", "staff")
    async with sessions() as s:
        await s.execute(
            update(Invite)
            .where(Invite.email == "vechi@t.ro")
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    async with client_factory() as guest:
        r = await guest.post(
            f"/api/invites/{accepted}/accept", json={"name": "Gata", "password": "parola-gata-1"}
        )
        assert r.status_code == 200

    r = await owner.get("/api/invites?location_id=test")
    assert r.status_code == 200, r.text
    items = r.json()
    assert [i["email"] for i in items] == ["ion@t.ro", "sef@t.ro"]  # newest first
    assert all(set(i) == FIELDS for i in items)  # never the token or its hash
    ion = items[0]
    assert ion["role"] == "staff" and ion["location_id"] == "test"
    assert ion["created_by"] == {"id": "u-manager", "name": "Mihai"}
    assert ion["id"] == await _id(sessions, "ion@t.ro")
    assert datetime.fromisoformat(ion["expires_at"]) > datetime.now(UTC)

    # a manager sees only the staff invites of their location
    mine = (await manager.get("/api/invites?location_id=test")).json()
    assert [i["email"] for i in mine] == ["ion@t.ro"]
    assert [i["email"] for i in (await manager.get("/api/invites")).json()] == ["ion@t.ro"]
    assert [i["email"] for i in (await other.get("/api/invites")).json()] == ["sala@t.ro"]

    assert (await staff.get("/api/invites?location_id=test")).status_code == 403
    assert (await manager.get("/api/invites?location_id=other")).status_code == 404
    assert (await xowner.get("/api/invites?location_id=test")).status_code == 404
    async with client_factory() as guest:
        assert (await guest.get("/api/invites")).status_code == 401
    for c in (owner, manager, staff, other, xowner):
        await c.aclose()


async def test_revoke_an_invite(t: Any, client_factory: Any, login: Any, sessions: Any) -> None:
    owner = await _as(client_factory, login, "owner@t.ro")
    manager = await _as(client_factory, login, "manager@t.ro")
    staff = await _as(client_factory, login, "staff@t.ro")
    other = await _as(client_factory, login, "other@t.ro")
    xowner = await _as(client_factory, login, "owner@x.ro")
    token = await _invite(manager, "ion@t.ro", "staff")
    await _invite(owner, "sef@t.ro", "manager")
    ion, sef = await _id(sessions, "ion@t.ro"), await _id(sessions, "sef@t.ro")

    r = await staff.delete(f"/api/invites/{ion}")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "forbidden"
    assert (await manager.delete(f"/api/invites/{sef}")).status_code == 403  # a manager invite
    for c in (other, xowner):
        r = await c.delete(f"/api/invites/{ion}")
        assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"
    assert (await manager.delete("/api/invites/inv-nope")).status_code == 404

    r = await manager.delete(f"/api/invites/{ion}")
    assert r.status_code == 204 and r.content == b""
    assert (await manager.delete(f"/api/invites/{ion}")).status_code == 204  # idempotent
    assert [i["id"] for i in (await owner.get("/api/invites")).json()] == [sef]
    assert (await owner.delete(f"/api/invites/{sef}")).status_code == 204
    assert (await owner.get("/api/invites")).json() == []

    async with client_factory() as guest:
        for r in (
            await guest.get(f"/api/invites/{token}"),
            await guest.post(
                f"/api/invites/{token}/accept", json={"name": "Ion", "password": "parola-ion-1"}
            ),
        ):
            assert r.status_code == 410, r.text
            assert r.json()["detail"] == {"code": "gone", "message_ro": "Invitația a fost anulată."}

    async with sessions() as s:
        rows = (
            await s.scalars(
                select(AuditRow).where(AuditRow.kind == "user.invite_revoked").order_by(AuditRow.id)
            )
        ).all()
    assert [(r.actor_id, r.target_label) for r in rows] == [
        ("u-manager", "ion@t.ro"),
        ("u-owner", "sef@t.ro"),
    ]  # once per invite, not per call
    assert rows[0].location_id == "test"
    assert rows[0].before["email"] == "ion@t.ro" and rows[0].before["role"] == "staff"
    assert "token" not in str(rows[0].before) and "hash" not in str(rows[0].before)
    assert rows[0].summary_ro == "Mihai a anulat invitația pentru ion@t.ro"
    for c in (owner, manager, staff, other, xowner):
        await c.aclose()


async def test_an_accepted_invite_cannot_be_revoked(
    t: Any, client_factory: Any, login: Any, sessions: Any
) -> None:
    manager = await _as(client_factory, login, "manager@t.ro")
    token = await _invite(manager, "ion@t.ro", "staff")
    async with client_factory() as guest:
        r = await guest.post(
            f"/api/invites/{token}/accept", json={"name": "Ion", "password": "parola-ion-1"}
        )
        assert r.status_code == 200
    r = await manager.delete(f"/api/invites/{await _id(sessions, 'ion@t.ro')}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "conflict"
    await manager.aclose()
