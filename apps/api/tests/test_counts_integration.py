"""Counts the dashboard cards show: alerts per rule per day (Reguli), cameras per location
(Locații) and whether each member gets push notifications (Echipă)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from aivee_api.db.models import Device, PushSubscriptionRow
from aivee_api.db.repositories import (
    CameraRepository,
    DeviceRepository,
    EventRepository,
    RuleRepository,
)
from aivee_contracts.events import AlertEvent
from aivee_contracts.geometry import CameraConfig, Zone
from aivee_contracts.rules import Action, Condition, Rule

pytestmark = pytest.mark.integration

TABLE = Zone.model_validate(
    {"id": "t1", "name": "Masa 1", "tag": "table", "polygon": [[0, 0], [0.3, 0], [0.3, 0.3]]}
)


def _rule(rule_id: str, camera_id: str) -> Rule:
    return Rule(
        id=rule_id,
        camera_id=camera_id,
        name=rule_id,
        prompt_ro="",
        zone_tag="table",
        all_of=[Condition(kind="pose", role="guest", pose="raised_hand")],
        action=Action(type="telegram"),
    )


def _event(event_id: str, rule_id: str, camera_id: str, at: datetime, state: str = "opened") -> Any:
    return AlertEvent(
        event_id=event_id,
        rule_id=rule_id,
        camera_id=camera_id,
        zone_id="t1",
        state=state,  # type: ignore[arg-type]
        at=at,
        summary_ro="Masa 1 așteaptă",
        snapshot=False,
    )


@pytest.fixture
async def world(sessions: Any, tenancy_factory: Any) -> datetime:
    """`test`: edge-01 (online) with cam1, cam2; edge-02 (offline) with cam3; rules r1 (cam1)
    and r2 (cam2). `other`: edge-o (online) with camo, rule ro. `far` (org-x): camfar, rfar.
    A clip camera on `test` (upload-01 / video-1) must never count."""
    await tenancy_factory(sessions)
    now = datetime.now(UTC)
    async with sessions() as s:
        devices, cameras, rules = DeviceRepository(s), CameraRepository(s), RuleRepository(s)
        for site, device, cams in [
            ("test", "edge-01", ["cam1", "cam2"]),
            ("test", "edge-02", ["cam3"]),
            ("test", "upload-01", ["video-1"]),
            ("other", "edge-o", ["camo"]),
            ("far", "edge-far", ["camfar"]),
        ]:
            await devices.ensure_device(site, device)
            for cam in cams:
                await cameras.upsert(
                    CameraConfig(id=cam, name=cam, source="rtsp://x", zones=[TABLE]), device
                )
        for rule_id, cam in [
            ("r1", "cam1"),
            ("r2", "cam2"),
            ("rv", "video-1"),
            ("ro", "camo"),
            ("rfar", "camfar"),
        ]:
            await rules.upsert(_rule(rule_id, cam))
        await s.flush()
        for d in ("edge-01", "edge-o", "edge-far", "upload-01"):
            (await s.get(Device, d)).state = "online"  # type: ignore[union-attr]
        events = EventRepository(s)
        day = timedelta(days=1)
        for event_id, rule_id, cam, device, at, state in [
            ("a1", "r1", "cam1", "edge-01", now, "opened"),
            ("a1c", "r1", "cam1", "edge-01", now, "closed"),  # not a new alert
            ("a2", "r1", "cam1", "edge-01", now - day, "opened"),
            ("a3", "r1", "cam1", "edge-01", now - 2 * day, "opened"),
            ("a4", "r1", "cam1", "edge-01", now - 6 * day, "opened"),
            ("a-old", "r1", "cam1", "edge-01", now - 8 * day, "opened"),  # outside 7 days
            ("v1", "rv", "video-1", "upload-01", now, "opened"),  # a clip: never counted
            ("o1", "ro", "camo", "edge-o", now, "opened"),
            ("f1", "rfar", "camfar", "edge-far", now, "opened"),
        ]:
            await events.insert_if_new(_event(event_id, rule_id, cam, at, state), device, None)
        s.add(
            PushSubscriptionRow(
                endpoint="https://push.example/ana", p256dh="k", auth="a", user_id="u-staff"
            )
        )
        await s.commit()
    return now


async def _client(client_factory: Any, login: Any, email: str) -> httpx.AsyncClient:
    c: httpx.AsyncClient = client_factory()
    await login(c, email)
    return c


async def test_rule_stats_count_alerts_per_day_at_the_location(
    world: datetime, client_factory: Any, login: Any
) -> None:
    manager = await _client(client_factory, login, "manager@t.ro")
    r = await manager.get("/api/rules/stats?days=7")
    assert r.status_code == 200, r.text
    body = r.json()
    today = world.date()
    assert body["days"] == [(today - timedelta(days=6 - i)).isoformat() for i in range(7)]
    stats = {x["rule_id"]: x for x in body["rules"]}
    assert set(stats) == {"r1", "r2"}  # no clip rules, nothing from other locations
    assert stats["r1"] == {"rule_id": "r1", "total": 4, "per_day": [1, 0, 0, 0, 1, 1, 1]}
    assert stats["r2"] == {"rule_id": "r2", "total": 0, "per_day": [0] * 7}
    await manager.aclose()


async def test_rule_stats_are_scoped_like_the_rules(
    world: datetime, client_factory: Any, login: Any
) -> None:
    owner = await _client(client_factory, login, "owner@t.ro")
    r = await owner.get("/api/rules/stats?location_id=other")
    assert [x["rule_id"] for x in r.json()["rules"]] == ["ro"]
    assert r.json()["rules"][0]["total"] == 1
    assert len(r.json()["days"]) == 7  # the default
    assert (await owner.get("/api/rules/stats?location_id=far")).status_code == 404
    assert (await owner.get("/api/rules/stats?days=0")).status_code == 422
    assert (await owner.get("/api/rules/stats?days=91")).status_code == 422
    staff = await _client(client_factory, login, "staff@t.ro")
    assert (await staff.get("/api/rules/stats")).status_code == 403
    for c in (owner, staff):
        await c.aclose()


async def test_locations_carry_camera_counts(
    world: datetime, client_factory: Any, login: Any
) -> None:
    owner = await _client(client_factory, login, "owner@t.ro")
    manager = await _client(client_factory, login, "manager@t.ro")
    counts = {
        x["id"]: (x["cameras_total"], x["cameras_online"])
        for x in (await owner.get("/api/locations")).json()
    }
    assert counts == {"test": (3, 2), "other": (1, 1)}  # clips do not count
    mine = (await manager.get("/api/locations")).json()
    assert [(x["id"], x["cameras_total"], x["cameras_online"]) for x in mine] == [("test", 3, 2)]
    for c in (owner, manager):
        await c.aclose()


async def test_members_say_who_gets_push(world: datetime, client_factory: Any, login: Any) -> None:
    manager = await _client(client_factory, login, "manager@t.ro")
    members = (await manager.get("/api/locations/test/members")).json()
    push = {m["email"]: m["push_enabled"] for m in members}
    assert push == {"owner@t.ro": False, "manager@t.ro": False, "staff@t.ro": True}
    await manager.aclose()
