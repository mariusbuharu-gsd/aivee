"""DELETE /api/cameras/{id}: camera, zones and rules go; events and alerts stay readable;
open alerts are closed by the system; the edge gets the new retained config and rules."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from aivee_api.alerts.repository import AlertRepository
from aivee_api.audit.models import AuditRow
from aivee_api.db.models import Camera, EventRow, RuleRow
from aivee_api.db.repositories import (
    CameraRepository,
    DeviceRepository,
    EventRepository,
    RuleRepository,
)
from aivee_api.edge.publisher import RecordingPublisher
from aivee_contracts.events import AlertEvent
from aivee_contracts.geometry import CameraConfig, Zone
from aivee_contracts.rules import Action, Condition, Rule
from aivee_contracts.topics import Topics
from sqlalchemy import func, select

pytestmark = pytest.mark.integration

TABLE = Zone.model_validate(
    {"id": "t1", "name": "Masa 1", "tag": "table", "polygon": [[0, 0], [0.3, 0], [0.3, 0.3]]}
)
T0 = datetime.now(UTC) - timedelta(minutes=10)


def _event(event_id: str, camera_id: str, state: str, at: datetime) -> AlertEvent:
    return AlertEvent(
        event_id=event_id,
        rule_id=f"r-{camera_id}",
        camera_id=camera_id,
        zone_id="t1",
        state=state,  # type: ignore[arg-type]
        at=at,
        summary_ro="Masa 1: neservită de 2 min",
    )


@pytest.fixture
async def world(sessions: Any, tenancy_factory: Any) -> None:
    """`test`: edge-01 with cam1 and cam2 (a rule each). cam1 has a closed alert (ev-done)
    and an open one (ev-open). `far` (org-x): edge-far with camfar."""
    await tenancy_factory(sessions)
    async with sessions() as s:
        for site, device, cams in [
            ("test", "edge-01", ["cam1", "cam2"]),
            ("far", "edge-far", ["camfar"]),
        ]:
            await DeviceRepository(s).ensure_device(site, device)
            for cam in cams:
                await CameraRepository(s).upsert(
                    CameraConfig(id=cam, name=f"Camera {cam}", source="rtsp://x", zones=[TABLE]),
                    device,
                )
                await RuleRepository(s).upsert(
                    Rule(
                        id=f"r-{cam}",
                        camera_id=cam,
                        name=f"Regula {cam}",
                        prompt_ro="",
                        zone_tag="table",
                        all_of=[Condition(kind="pose", role="guest", pose="raised_hand")],
                        action=Action(type="telegram"),
                    )
                )
        events = [
            _event("ev-done", "cam1", "opened", T0),
            _event("ev-done-c", "cam1", "closed", T0 + timedelta(minutes=1)),
            _event("ev-open", "cam1", "opened", T0 + timedelta(minutes=2)),
        ]
        for e in events:
            await EventRepository(s).insert_if_new(e, "edge-01")
            await AlertRepository(s).link(e, "edge-01")
        await s.commit()


async def _as(client_factory: Any, login: Any, email: str) -> httpx.AsyncClient:
    c: httpx.AsyncClient = client_factory()
    await login(c, email)
    return c


def _retained(publisher: RecordingPublisher, leaf: str) -> dict[str, Any]:
    topic = getattr(Topics(site="test", device="edge-01"), leaf)
    msg = publisher.last(topic)
    assert msg is not None and msg.retain, leaf
    data: dict[str, Any] = json.loads(msg.payload)
    return data


async def test_who_may_delete_a_camera(world: None, client_factory: Any, login: Any) -> None:
    staff = await _as(client_factory, login, "staff@t.ro")
    other = await _as(client_factory, login, "other@t.ro")  # manager of `other`, same org
    xowner = await _as(client_factory, login, "owner@x.ro")
    r = await staff.delete("/api/cameras/cam1")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "forbidden"
    for c in (other, xowner):
        r = await c.delete("/api/cameras/cam1")
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "not_found"
    manager = await _as(client_factory, login, "manager@t.ro")
    assert (await manager.delete("/api/cameras/camfar")).status_code == 404
    assert (await manager.delete("/api/cameras/nope")).status_code == 404
    assert (await manager.get("/api/cameras/cam1")).status_code == 200  # nothing deleted
    for c in (staff, other, xowner, manager):
        await c.aclose()


async def test_manager_deletes_a_camera_and_the_history_stays(
    world: None,
    client_factory: Any,
    login: Any,
    sessions: Any,
    publisher: RecordingPublisher,
) -> None:
    manager = await _as(client_factory, login, "manager@t.ro")
    publisher.messages.clear()

    r = await manager.delete("/api/cameras/cam1")
    assert r.status_code == 204, r.text
    assert (await manager.get("/api/cameras/cam1")).status_code == 404
    assert (await manager.delete("/api/cameras/cam1")).status_code == 404
    assert [c["id"] for c in (await manager.get("/api/cameras")).json()] == ["cam2"]

    # the edge drops the camera and its rule
    config = _retained(publisher, "config")
    assert [c["id"] for c in config["cameras"]] == ["cam2"]
    rules = _retained(publisher, "rules")
    assert [x["id"] for x in rules["rules"]] == ["r-cam2"]

    async with sessions() as s:
        assert await s.get(Camera, "cam1") is None
        assert await s.get(RuleRow, "r-cam1") is None
        assert await s.get(RuleRow, "r-cam2") is not None
        kept = await s.scalar(select(func.count()).where(EventRow.camera_id == "cam1"))
        assert kept == 4  # three edge events + the system's closed row
        audit = (await s.scalars(select(AuditRow).order_by(AuditRow.id))).all()

    # both alerts stay readable; the open one was closed by the system
    alerts = {a["event_id"]: a for a in (await manager.get("/api/alerts")).json()}
    assert set(alerts) == {"ev-done", "ev-open"}
    assert alerts["ev-done"]["closed_by"] == "edge"
    assert alerts["ev-done"]["closed_reason"] is None
    assert alerts["ev-open"]["state"] == "closed"
    assert alerts["ev-open"]["closed_by"] == "system"
    assert alerts["ev-open"]["closed_reason"] == "camera_deleted"
    assert alerts["ev-open"]["location_id"] == "test"
    assert alerts["ev-open"]["zone_name"] == "Masa 1"
    assert (await manager.get("/api/alerts?state=open")).json() == []

    closed = [a for a in audit if a.kind == "alert.closed"]
    assert len(closed) == 1
    assert closed[0].actor_kind == "system" and closed[0].target_id == "ev-open"
    assert closed[0].after == {"reason": "camera_deleted"}
    assert "camera a fost ștearsă" in closed[0].summary_ro
    deleted = [a for a in audit if a.kind == "camera.deleted"]
    assert len(deleted) == 1
    entry = deleted[0]
    assert entry.actor_id == "u-manager" and entry.location_id == "test"
    assert entry.target_id == "cam1" and entry.target_label == "Camera cam1"
    assert entry.before["id"] == "cam1" and entry.before["zones"][0]["id"] == "t1"
    assert entry.after is None
    assert entry.summary_ro == "Mihai a șters camera Camera cam1"
    await manager.aclose()


async def test_owner_deletes_a_camera_without_open_alerts(
    world: None,
    client_factory: Any,
    login: Any,
    sessions: Any,
    publisher: RecordingPublisher,
) -> None:
    owner = await _as(client_factory, login, "owner@t.ro")
    assert (await owner.delete("/api/cameras/cam2")).status_code == 204
    config = _retained(publisher, "config")
    assert [c["id"] for c in config["cameras"]] == ["cam1"]
    async with sessions() as s:
        kinds = list(await s.scalars(select(AuditRow.kind).order_by(AuditRow.id)))
    assert kinds[-1] == "camera.deleted" and "alert.closed" not in kinds
    alerts = (await owner.get("/api/alerts?state=open")).json()
    assert [a["event_id"] for a in alerts] == ["ev-open"]  # cam1's alert is untouched
    await owner.aclose()
