"""Existing endpoints filtered by membership: another location → 404, missing permission → 403,
and /ws/events authenticated by the cookie and limited to the user's locations."""

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from aivee_api.alerts.repository import AlertRepository
from aivee_api.audit.models import AuditRow
from aivee_api.db.repositories import (
    CameraRepository,
    DeviceRepository,
    EventRepository,
    RuleRepository,
    SuggestionRepository,
)
from aivee_api.db.session import make_session_factory
from aivee_api.main import create_app
from aivee_contracts.events import AlertEvent, StaffSuggestion
from aivee_contracts.geometry import CameraConfig, Zone
from aivee_contracts.rules import Action, Condition, Rule
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

pytestmark = pytest.mark.integration

JPEG = b"\xff\xd8\xff\xe0fake-jpeg\xff\xd9"
TABLE = Zone.model_validate(
    {"id": "t1", "name": "Masa 1", "tag": "table", "polygon": [[0, 0], [0.3, 0], [0.3, 0.3]]}
)
RULE_BODY = {
    "camera_id": "cam1",
    "name": "Mâna ridicată",
    "zone_tag": "table",
    "all_of": [{"kind": "pose", "role": "guest", "pose": "raised_hand"}],
}


def _event(event_id: str, camera_id: str) -> AlertEvent:
    return AlertEvent(
        event_id=event_id,
        rule_id="r1",
        camera_id=camera_id,
        zone_id="t1",
        state="opened",
        at=datetime.now(UTC),
        summary_ro="Masa 1 așteaptă",
        snapshot=True,
    )


async def seed_world(sessions: Any, tenancy_factory: Any) -> None:
    """`test`: edge-01, cam1, rule r-test, event ev-test, suggestion s-test.
    `far` (org-x): edge-far, camfar, rule r-far, event ev-far, suggestion s-far."""
    await tenancy_factory(sessions)
    async with sessions() as s:
        devices, cameras, rules = (
            DeviceRepository(s),
            CameraRepository(s),
            RuleRepository(s),
        )
        for site, device, cam, rule, ev, sugg in [
            ("test", "edge-01", "cam1", "r-test", "ev-test", "s-test"),
            ("far", "edge-far", "camfar", "r-far", "ev-far", "s-far"),
        ]:
            await devices.ensure_device(site, device)
            await cameras.upsert(
                CameraConfig(id=cam, name=f"Cam {site}", source="rtsp://x", zones=[TABLE]), device
            )
            await rules.upsert(
                Rule(
                    id=rule,
                    camera_id=cam,
                    name=f"Regula {site}",
                    prompt_ro="",
                    zone_tag="table",
                    all_of=[Condition(kind="pose", role="guest", pose="raised_hand")],
                    action=Action(type="telegram"),
                )
            )
            await EventRepository(s).insert_if_new(_event(ev, cam), device, f"{ev}.jpg")
            await SuggestionRepository(s).insert_if_new(
                StaffSuggestion(
                    suggestion_id=sugg, camera_id=cam, track_id=1, staff_score=0.8, reason_ro="x"
                ),
                device,
            )
        await s.commit()


@pytest.fixture
async def world(sessions: Any, tenancy_factory: Any) -> None:
    await seed_world(sessions, tenancy_factory)


async def _client(client_factory: Any, login: Any, email: str) -> httpx.AsyncClient:
    c: httpx.AsyncClient = client_factory()
    await login(c, email)
    return c


async def test_another_locations_data_is_404(world: None, client_factory: Any, login: Any) -> None:
    manager = await _client(client_factory, login, "manager@t.ro")
    xowner = await _client(client_factory, login, "owner@x.ro")
    for path in (
        "/api/cameras/camfar",
        "/api/cameras/camfar/zones",
        "/api/rules/r-far",
        "/api/cameras?location_id=far",
        "/api/events?location_id=far",
        "/api/devices?location_id=other",  # same org, not the manager's location
        "/api/metrics?location_id=far",
        "/api/rules?location_id=far",
        "/api/staff/suggestions?location_id=far",
        "/api/snapshots/ev-far",
        "/api/snapshots/ev-far-before",
        "/api/snapshots/s-far",
    ):
        r = await manager.get(path)
        assert r.status_code == 404, path
        assert r.json()["detail"]["code"] == "not_found"
    assert (await manager.put("/api/cameras/camfar/zones", json=[])).status_code == 404
    assert (await manager.patch("/api/rules/r-far", json={"enabled": False})).status_code == 404
    assert (await manager.delete("/api/rules/r-far")).status_code == 404
    assert (
        await manager.post("/api/rules", json={**RULE_BODY, "camera_id": "camfar"})
    ).status_code == 404
    assert (await manager.post("/api/staff/suggestions/s-far/confirm")).status_code == 404
    # ... and the other org cannot see `test`
    assert (await xowner.get("/api/cameras/cam1")).status_code == 404
    assert (await xowner.get("/api/events?location_id=test")).status_code == 404
    # an explicit id must not overwrite another org's rule
    r = await xowner.post("/api/rules", json={**RULE_BODY, "camera_id": "camfar", "id": "r-test"})
    assert r.status_code == 409
    for c in (manager, xowner):
        await c.aclose()


async def test_lists_only_show_the_callers_location(
    world: None, client_factory: Any, login: Any
) -> None:
    manager = await _client(client_factory, login, "manager@t.ro")
    assert [c["id"] for c in (await manager.get("/api/cameras")).json()] == ["cam1"]
    assert [e["event_id"] for e in (await manager.get("/api/events")).json()] == ["ev-test"]
    assert [r["id"] for r in (await manager.get("/api/rules")).json()] == ["r-test"]
    assert [d["device"] for d in (await manager.get("/api/devices")).json()] == ["edge-01"]
    sugg = (await manager.get("/api/staff/suggestions")).json()
    assert [x["suggestion_id"] for x in sugg] == ["s-test"]
    assert (await manager.get("/api/metrics")).json()["events_today"] == 1
    await manager.aclose()


async def test_staff_is_403_on_rules_and_config(
    world: None, client_factory: Any, login: Any
) -> None:
    staff = await _client(client_factory, login, "staff@t.ro")
    assert (await staff.get("/api/cameras")).status_code == 200  # alerts.view: live view
    assert (await staff.get("/api/events")).status_code == 200
    for method, path, body in [
        ("GET", "/api/rules", None),
        ("POST", "/api/rules", RULE_BODY),
        ("GET", "/api/rules/r-test", None),
        ("PATCH", "/api/rules/r-test", {"enabled": False}),
        ("DELETE", "/api/rules/r-test", None),
        ("POST", "/api/rules/from-text", {"camera_id": "cam1", "text": "nimeni la masă"}),
        ("PUT", "/api/cameras/cam1/zones", []),
        ("POST", "/api/cameras", {"name": "X", "source": "rtsp://y"}),
        ("GET", "/api/staff/suggestions", None),
        ("POST", "/api/staff/suggestions/s-test/confirm", None),
        ("GET", "/api/staff/profiles", None),
        ("POST", "/api/staff/photos", None),
    ]:
        r = await staff.request(method, path, json=body)
        assert r.status_code == 403, (method, path, r.text)
        assert r.json()["detail"]["code"] == "forbidden"
    await staff.aclose()


async def test_snapshots_follow_the_event_location(
    world: None, client_factory: Any, login: Any, settings: Any
) -> None:
    (settings.snapshot_dir / "ev-test.jpg").write_bytes(JPEG)
    (settings.snapshot_dir / "s-test.jpg").write_bytes(JPEG)
    staff = await _client(client_factory, login, "staff@t.ro")
    manager = await _client(client_factory, login, "manager@t.ro")
    r = await staff.get("/api/snapshots/ev-test")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content == JPEG
    assert (await staff.get("/api/snapshots/s-test")).status_code == 403  # staff.review
    assert (await manager.get("/api/snapshots/s-test")).status_code == 200
    # The "before" image of an object change follows its event too.
    assert (await staff.get("/api/snapshots/ev-test-before")).status_code == 404  # no file yet
    (settings.snapshot_dir / "ev-test-before.jpg").write_bytes(JPEG)
    assert (await staff.get("/api/snapshots/ev-test-before")).content == JPEG
    for bad in ("missing", "..%2F..%2Fetc%2Fpasswd", "a.b"):
        assert (await staff.get(f"/api/snapshots/{bad}")).status_code == 404
    for c in (staff, manager):
        await c.aclose()


async def test_config_changes_are_audited_with_before_and_after(
    world: None, client_factory: Any, login: Any, sessions: Any
) -> None:
    manager = await _client(client_factory, login, "manager@t.ro")
    r = await manager.post("/api/rules", json=RULE_BODY)
    assert r.status_code == 201
    rid = r.json()["id"]
    await manager.patch(f"/api/rules/{rid}", json={"cooldown_s": 90})
    await manager.delete(f"/api/rules/{rid}")
    door = {
        "id": "e1",
        "name": "Intrare",
        "tag": "entrance",
        "polygon": [[0.6, 0], [1, 0], [1, 0.4]],
    }
    assert (await manager.put("/api/cameras/cam1/zones", json=[door])).status_code == 200
    assert (await manager.post("/api/staff/suggestions/s-test/reject")).status_code == 200
    r = await manager.post("/api/cameras", json={"id": "cam2", "name": "Bar", "source": "rtsp://z"})
    assert r.status_code == 201, r.text
    async with sessions() as s:
        rows = (
            await s.scalars(
                select(AuditRow).where(AuditRow.kind != "auth.login").order_by(AuditRow.id)
            )
        ).all()
    assert [(r.kind, r.location_id, r.actor_id) for r in rows] == [
        ("rule.created", "test", "u-manager"),
        ("rule.updated", "test", "u-manager"),
        ("rule.deleted", "test", "u-manager"),
        ("zones.updated", "test", "u-manager"),
        ("staff.rejected", "test", "u-manager"),
        ("camera.created", "test", "u-manager"),
    ]
    assert rows[1].before["cooldown_s"] == 300 and rows[1].after["cooldown_s"] == 90
    assert [z["id"] for z in rows[3].before] == ["t1"] and [z["id"] for z in rows[3].after] == [
        "e1"
    ]
    assert rows[0].summary_ro == "Mihai a creat regula „Mâna ridicată”"
    assert rows[4].summary_ro == "Mihai a respins o sugestie de personal pe camera Cam test"
    await manager.aclose()


def test_ws_events_needs_the_cookie_and_streams_only_own_locations(
    db_url: str,
    settings: Any,
    publisher: Any,
    translator: Any,
    services_factory: Any,
    tenancy_factory: Any,
) -> None:
    # NullPool: the TestClient runs the app on its own event loop; no connection is shared.
    engine = create_async_engine(db_url, poolclass=NullPool)
    sessions = make_session_factory(engine)
    asyncio.run(seed_world(sessions, tenancy_factory))
    app = create_app(services_factory(settings, sessions, publisher, translator))
    app.state.ws_poll_interval_s = 0.05

    async def add_events(*pairs: tuple[str, str]) -> None:
        async with sessions() as s:
            for event_id, device in pairs:
                cam = "cam1" if device == "edge-01" else "camfar"
                event = _event(event_id, cam)
                await EventRepository(s).insert_if_new(event, device)
                await AlertRepository(s).link(event, device)
            await s.commit()

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as denied, client.websocket_connect("/ws/events"):
            pass
        assert denied.value.code == 1008
        client.cookies.set("aivee_session", "forged-token")
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/events"):
            pass

        r = client.post(
            "/api/auth/login", json={"email": "staff@t.ro", "password": "parola-test-1"}
        )
        assert r.status_code == 200
        with client.websocket_connect("/ws/events") as ws:
            time.sleep(0.2)  # let the feed take its starting cursor
            asyncio.run(add_events(("ev-far-2", "edge-far"), ("ev-test-2", "edge-01")))
            # Raw row and folded AlertView come from two polls, so either may arrive first.
            first, second = ws.receive_json(), ws.receive_json()
        folded, raw = sorted([first, second], key=lambda m: "location_id" not in m["data"])
        assert raw["type"] == "alert" and raw["data"]["event_id"] == "ev-test-2"
        # The folded AlertView of the same alert, also only of the user's location.
        assert folded["type"] == "alert" and folded["data"]["event_id"] == "ev-test-2"
        assert folded["data"]["location_id"] == "test" and "zone_name" in folded["data"]
    asyncio.run(engine.dispose())
