"""Routers against a real Postgres (testcontainers) with a recording edge publisher."""

import json
import math
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from aivee_api.db.repositories import (
    DeviceRepository,
    EventRepository,
    StaffRepository,
    SuggestionRepository,
)
from aivee_api.deps import Services
from aivee_api.edge.publisher import RecordingPublisher
from aivee_api.edge.sync import LoggingEdgeCommands
from aivee_api.events.service import LiveFeed
from aivee_api.main import create_app
from aivee_api.rules.translator import TranslationError
from aivee_api.settings import ApiSettings
from aivee_api.staff.enrol import Enroller
from aivee_contracts.events import AlertEvent, DeviceStatus, Metrics, StaffSuggestion
from aivee_contracts.geometry import DeviceConfig
from aivee_contracts.rules import RuleSet
from aivee_contracts.topics import Topics

pytestmark = pytest.mark.integration

TOPICS = Topics(site="test", device="edge-01")
TABLE = {"id": "t1", "name": "Masa 1", "tag": "table", "polygon": [[0, 0], [0.3, 0], [0.3, 0.3]]}
DOOR = {"id": "e1", "name": "Intrare", "tag": "entrance", "polygon": [[0.6, 0], [1, 0], [1, 0.4]]}


@pytest.fixture
def services(
    settings: ApiSettings,
    sessions: Any,
    publisher: RecordingPublisher,
    translator: Any,
    fake_enroller: Enroller,
    services_factory: Any,
) -> Services:
    svc: Services = services_factory(settings, sessions, publisher, translator, fake_enroller)
    return svc


@pytest.fixture
async def api(services: Services) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(services)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _retained(publisher: RecordingPublisher, topic: str) -> dict[str, Any]:
    msg = publisher.last(topic)
    assert msg is not None, f"nothing published on {topic}"
    assert (msg.qos, msg.retain) == (1, True)
    data: dict[str, Any] = json.loads(msg.payload)
    return data


async def _camera(api: httpx.AsyncClient, zones: list[dict[str, Any]] | None = None) -> str:
    r = await api.post(
        "/api/cameras",
        json={"id": "cam1", "name": "Sala", "source": "rtsp://x", "zones": zones or [TABLE]},
    )
    assert r.status_code == 201, r.text
    return "cam1"


def _rule_body(**overrides: Any) -> dict[str, Any]:
    body = {
        "camera_id": "cam1",
        "name": "Mâna ridicată",
        "zone_tag": "table",
        "all_of": [{"kind": "pose", "role": "guest", "pose": "raised_hand"}],
        "cooldown_s": 60,
    }
    return {**body, **overrides}


async def test_camera_and_zones_publish_the_full_device_config(
    api: httpx.AsyncClient, publisher: RecordingPublisher
) -> None:
    await _camera(api)
    config = DeviceConfig.model_validate(_retained(publisher, TOPICS.config))
    assert [c.id for c in config.cameras] == ["cam1"]

    r = await api.put("/api/cameras/cam1/zones", json=[TABLE, DOOR])
    assert r.status_code == 200
    config = DeviceConfig.model_validate(_retained(publisher, TOPICS.config))
    assert [z.id for z in config.cameras[0].zones] == ["t1", "e1"]

    cameras = (await api.get("/api/cameras")).json()
    assert cameras[0]["device"] == "edge-01" and cameras[0]["online"] is False
    assert [z["id"] for z in (await api.get("/api/cameras/cam1/zones")).json()] == ["t1", "e1"]


async def test_creating_an_existing_camera_is_409_and_keeps_it(api: httpx.AsyncClient) -> None:
    await _camera(api)
    r = await api.post("/api/cameras", json={"id": "cam1", "name": "Alta", "source": "rtsp://y"})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "conflict" and "cam1" in detail["message_ro"]
    camera = (await api.get("/api/cameras/cam1")).json()
    assert (camera["name"], camera["source"], len(camera["zones"])) == ("Sala", "rtsp://x", 1)


async def test_camera_create_takes_an_optional_device(
    api: httpx.AsyncClient, publisher: RecordingPublisher
) -> None:
    r = await api.post(
        "/api/cameras",
        json={"id": "cam2", "name": "Terasa", "source": "rtsp://t", "device": "edge-02"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["device"] == "edge-02"
    other = DeviceConfig.model_validate(
        _retained(publisher, Topics(site="test", device="edge-02").config)
    )
    assert [c.id for c in other.cameras] == ["cam2"]
    await _camera(api)  # no device: the API's DEVICE
    assert (await api.get("/api/cameras/cam1")).json()["device"] == "edge-01"
    default = DeviceConfig.model_validate(_retained(publisher, TOPICS.config))
    assert [c.id for c in default.cameras] == ["cam1"]


@pytest.mark.parametrize("method", ["PUT", "PATCH"])
async def test_updating_a_camera_keeps_its_zones(
    api: httpx.AsyncClient, publisher: RecordingPublisher, method: str
) -> None:
    await _camera(api, [TABLE, DOOR])
    r = await api.request(
        method, "/api/cameras/cam1", json={"name": "Sala mare", "source": "rtsp://nou"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["name"], body["source"], body["device"]) == ("Sala mare", "rtsp://nou", "edge-01")
    assert [z["id"] for z in body["zones"]] == ["t1", "e1"]
    [camera] = DeviceConfig.model_validate(_retained(publisher, TOPICS.config)).cameras
    assert (camera.name, [z.id for z in camera.zones]) == ("Sala mare", ["t1", "e1"])


async def test_moving_a_camera_republishes_both_devices(
    api: httpx.AsyncClient, publisher: RecordingPublisher
) -> None:
    await _camera(api)
    rule = (await api.post("/api/rules", json=_rule_body())).json()
    r = await api.patch("/api/cameras/cam1", json={"device": "edge-02"})
    assert r.status_code == 200 and r.json()["device"] == "edge-02"

    other = Topics(site="test", device="edge-02")
    assert DeviceConfig.model_validate(_retained(publisher, TOPICS.config)).cameras == []
    assert RuleSet.model_validate(_retained(publisher, TOPICS.rules)).rules == []
    moved = DeviceConfig.model_validate(_retained(publisher, other.config))
    assert [c.id for c in moved.cameras] == ["cam1"]
    rules = RuleSet.model_validate(_retained(publisher, other.rules))
    assert (rules.device, [r.id for r in rules.rules]) == ("edge-02", [rule["id"]])


async def test_camera_update_errors(api: httpx.AsyncClient) -> None:
    r = await api.patch("/api/cameras/nope", json={"name": "X"})
    assert r.status_code == 404 and r.json()["detail"]["message_ro"]
    await _camera(api)
    assert (await api.patch("/api/cameras/cam1", json={"name": ""})).status_code == 422
    assert (await api.patch("/api/cameras/cam1", json={"device": "a/b"})).status_code == 422


async def test_zone_errors(api: httpx.AsyncClient) -> None:
    assert (await api.put("/api/cameras/nope/zones", json=[TABLE])).status_code == 404
    await _camera(api)
    r = await api.put("/api/cameras/cam1/zones", json=[TABLE, TABLE])
    assert r.status_code == 422
    assert r.json()["detail"]["message_ro"]


async def test_camera_online_follows_device_status(api: httpx.AsyncClient, sessions: Any) -> None:
    await _camera(api)
    async with sessions() as s:
        await DeviceRepository(s).apply_status(
            "test", DeviceStatus(device="edge-01", state="online")
        )
        await s.commit()
    assert (await api.get("/api/cameras")).json()[0]["online"] is True
    [device] = (await api.get("/api/devices")).json()
    assert (device["device"], device["state"], device["site"]) == ("edge-01", "online", "test")


async def test_rule_crud_publishes_the_complete_rule_set(
    api: httpx.AsyncClient, publisher: RecordingPublisher
) -> None:
    await _camera(api)
    r1 = (await api.post("/api/rules", json=_rule_body())).json()
    r2 = (await api.post("/api/rules", json=_rule_body(name="Alta", cooldown_s=90))).json()
    rules = RuleSet.model_validate(_retained(publisher, TOPICS.rules)).rules
    assert [r.id for r in rules] == [r1["id"], r2["id"]]

    r = await api.patch(f"/api/rules/{r1['id']}", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    rules = RuleSet.model_validate(_retained(publisher, TOPICS.rules)).rules
    assert [(r.id, r.enabled) for r in rules] == [(r1["id"], False), (r2["id"], True)]

    assert (await api.delete(f"/api/rules/{r1['id']}")).status_code == 204
    rules = RuleSet.model_validate(_retained(publisher, TOPICS.rules)).rules
    assert [r.id for r in rules] == [r2["id"]]
    assert [r["id"] for r in (await api.get("/api/rules")).json()] == [r2["id"]]
    assert (await api.delete(f"/api/rules/{r1['id']}")).status_code == 404


async def test_rule_for_unknown_camera_is_404(api: httpx.AsyncClient) -> None:
    r = await api.post("/api/rules", json=_rule_body(camera_id="ghost"))
    assert r.status_code == 404


async def test_from_text_returns_a_draft_without_saving(
    api: httpx.AsyncClient, publisher: RecordingPublisher, translator: Any
) -> None:
    await _camera(api)
    before = len(publisher.messages)
    r = await api.post(
        "/api/rules/from-text", json={"camera_id": "cam1", "text": "Anunță ospătarul..."}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] is False
    assert body["explanation_ro"]
    assert body["rule"]["camera_id"] == "cam1"
    assert body["rule"]["prompt_ro"] == "Anunță ospătarul..."
    assert len(publisher.messages) == before
    assert (await api.get("/api/rules")).json() == []
    assert [z.id for z in translator.calls[0][1]] == ["t1"]

    r = await api.post("/api/rules", json=body["rule"])  # owner accepts the draft
    assert r.status_code == 201
    assert len(RuleSet.model_validate(_retained(publisher, TOPICS.rules)).rules) == 1


async def test_from_text_with_save_publishes(
    api: httpx.AsyncClient, publisher: RecordingPublisher
) -> None:
    await _camera(api)
    r = await api.post(
        "/api/rules/from-text", json={"camera_id": "cam1", "text": "nimeni la masă", "save": True}
    )
    assert r.status_code == 200 and r.json()["saved"] is True
    [rule] = RuleSet.model_validate(_retained(publisher, TOPICS.rules)).rules
    assert rule.id == r.json()["rule"]["id"]


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (TranslationError("clarify", "Ce masă?"), 422),
        (TranslationError("refusal", "Nu."), 422),
        (TranslationError("rate_limited", "Mai târziu."), 429),
        (TranslationError("unavailable", "Indisponibil."), 503),
    ],
)
async def test_from_text_errors_are_romanian(
    api: httpx.AsyncClient, translator: Any, error: TranslationError, status: int
) -> None:
    await _camera(api)
    translator.error = error
    r = await api.post("/api/rules/from-text", json={"camera_id": "cam1", "text": "ceva"})
    assert r.status_code == status
    assert r.json()["detail"] == {"code": error.code, "message_ro": error.message_ro}


async def test_events_list_and_live_feed(api: httpx.AsyncClient, sessions: Any) -> None:
    feed = LiveFeed(sessions)
    await feed.start()
    assert await feed.poll() == []
    event = AlertEvent(
        event_id="ev-1",
        rule_id="r1",
        camera_id="cam1",
        zone_id="t1",
        state="opened",
        at=datetime.now(UTC) - timedelta(milliseconds=400),
        summary_ro="Masa 1 așteaptă",
        snapshot=True,
    )
    suggestion = StaffSuggestion(
        suggestion_id="s-1", camera_id="cam1", track_id=7, staff_score=0.8, reason_ro="merge mult"
    )
    async with sessions() as s:
        await EventRepository(s).insert_if_new(event, "edge-01", "ev-1.jpg")
        await SuggestionRepository(s).insert_if_new(suggestion, "edge-01")
        await s.commit()

    [alert, sugg] = await feed.poll()
    assert alert.model_dump(mode="json")["type"] == "alert"
    assert alert.model_dump()["data"]["event_id"] == "ev-1"
    assert sugg.model_dump()["type"] == "suggestion"
    assert sugg.model_dump()["data"]["suggestion_id"] == "s-1"
    assert await feed.poll() == []

    [row] = (await api.get("/api/events?limit=5")).json()
    assert row["event_id"] == "ev-1" and row["snapshot_url"] == "/api/snapshots/ev-1"

    metrics = (await api.get("/api/metrics")).json()
    assert metrics["events_today"] == 1
    assert metrics["alert_latency_ms"] is not None and metrics["alert_latency_ms"] >= 0


async def test_metrics_combines_devices_and_cache(
    api: httpx.AsyncClient, services: Services, sessions: Any
) -> None:
    async with sessions() as s:
        await DeviceRepository(s).apply_status(
            "test", DeviceStatus(device="edge-01", state="online")
        )
        await DeviceRepository(s).apply_status(
            "test", DeviceStatus(device="edge-02", state="offline")
        )
        await s.commit()
    services.metrics.put("test", Metrics(device="edge-01", fps=9, verified_ratio=0, cpu_percent=50))
    m = (await api.get("/api/metrics")).json()
    assert (m["devices_online"], m["devices_total"], m["events_today"]) == (1, 2, 0)
    assert m["devices"][0]["fps"] == 9
    assert m["alert_latency_ms"] is None


async def _suggestion(sessions: Any, suggestion_id: str | None = None) -> str:
    sid = suggestion_id or f"s-{uuid.uuid4().hex[:6]}"
    async with sessions() as s:
        await SuggestionRepository(s).insert_if_new(
            StaffSuggestion(
                suggestion_id=sid, camera_id="cam1", track_id=3, staff_score=0.7, reason_ro="x"
            ),
            "edge-01",
        )
        await s.commit()
    return sid


async def test_confirm_and_reject_suggestions(
    api: httpx.AsyncClient, sessions: Any, services: Services, publisher: RecordingPublisher
) -> None:
    keep = await _suggestion(sessions)
    drop = await _suggestion(sessions)
    assert {s["suggestion_id"] for s in (await api.get("/api/staff/suggestions")).json()} == {
        keep,
        drop,
    }
    r = await api.post(f"/api/staff/suggestions/{keep}/confirm")
    assert r.json() == {"suggestion_id": keep, "status": "confirmed", "examples_added": 0}
    assert (await api.post(f"/api/staff/suggestions/{drop}/reject")).json()["status"] == "rejected"
    assert (await api.get("/api/staff/suggestions")).json() == []
    assert (await api.post(f"/api/staff/suggestions/{keep}/reject")).status_code == 409
    assert (await api.post("/api/staff/suggestions/nope/confirm")).status_code == 404
    commands = services.commands
    assert isinstance(commands, LoggingEdgeCommands)
    assert [(d.suggestion_id, d.confirmed, d.device_id) for d in commands.decisions] == [
        (keep, True, "edge-01"),
        (drop, False, "edge-01"),
    ]
    assert publisher.last(TOPICS.profiles) is None  # no snapshot → nothing learned


async def test_confirm_with_snapshot_learns_the_crop(
    api: httpx.AsyncClient, sessions: Any, settings: ApiSettings, publisher: RecordingPublisher
) -> None:
    sid = await _suggestion(sessions)
    (settings.snapshot_dir / f"{sid}.jpg").write_bytes(bytes([8]))
    r = await api.post(f"/api/staff/suggestions/{sid}/confirm")
    assert r.json()["examples_added"] == 1
    [profile] = _retained(publisher, TOPICS.profiles)["profiles"]
    assert profile["id"] == settings.default_profile_id


async def test_photo_enrolment_stores_examples_and_publishes_a_normalised_centroid(
    api: httpx.AsyncClient, sessions: Any, publisher: RecordingPublisher
) -> None:
    files = [
        ("photo", ("a.jpg", bytes([2]), "image/jpeg")),
        ("photo", ("b.jpg", bytes([4]), "image/jpeg")),
        ("files", ("clip.mp4", bytes([1, 6, 3]), "video/mp4")),
    ]
    r = await api.post(
        "/api/staff/photos",
        files=files,
        data={"profile_id": "waiter", "name": "Ospătar", "description_ro": "tricou vișiniu"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["files"], body["frames"], body["examples_added"]) == (3, 5, 3)
    assert body["profile"] == {
        "id": "waiter",
        "name": "Ospătar",
        "description_ro": "tricou vișiniu",
        "examples": 3,
        "has_centroid": True,
    }
    assert body["published"] is True

    [profile] = _retained(publisher, TOPICS.profiles)["profiles"]
    centroid = profile["centroid"]
    assert math.isclose(math.sqrt(sum(v * v for v in centroid)), 1.0, rel_tol=1e-5)
    assert centroid[2] > 0 and centroid[4] > 0 and centroid[6] > 0

    one_hot = [0.0] * 512
    one_hot[4] = 1.0
    async with sessions() as s:
        nearest = await StaffRepository(s).nearest_profile(one_hot)
    assert nearest is not None and nearest[0].id == "waiter"


async def test_photo_enrolment_rejects_bad_input(api: httpx.AsyncClient) -> None:
    r = await api.post("/api/staff/photos", files=[("photo", ("a.txt", b"hi", "text/plain"))])
    assert r.status_code == 422
    assert (await api.post("/api/staff/photos")).status_code == 422


async def test_enrolment_without_models_is_503(
    settings: ApiSettings,
    sessions: Any,
    publisher: RecordingPublisher,
    translator: Any,
    services_factory: Any,
) -> None:
    app = create_app(services_factory(settings, sessions, publisher, translator, None))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/staff/photos", files=[("photo", ("a.jpg", bytes([2]), "image/jpeg"))]
        )
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["code"] == "unavailable" and "Înrolarea" in detail["message_ro"]


class _NoWeights:
    def embed(self, crop: Any) -> list[float]:
        raise RuntimeError("Failed to download weights: Permission denied")


async def test_enrolment_models_that_fail_to_load_are_503(
    settings: ApiSettings,
    sessions: Any,
    publisher: RecordingPublisher,
    translator: Any,
    services_factory: Any,
    fake_enroller: Enroller,
) -> None:
    broken = Enroller(fake_enroller._decoder, fake_enroller._cropper, _NoWeights())
    app = create_app(services_factory(settings, sessions, publisher, translator, broken))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/staff/photos", files=[("photo", ("a.jpg", bytes([2]), "image/jpeg"))]
        )
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["code"] == "unavailable" and "modelele" in detail["message_ro"]
    async with sessions() as s:
        assert await StaffRepository(s).profiles() == []


async def test_publish_all_sends_every_retained_document(
    api: httpx.AsyncClient, services: Services, publisher: RecordingPublisher
) -> None:
    await _camera(api)
    publisher.messages.clear()
    await services.sync.publish_all()
    assert {m.topic for m in publisher.messages} == {TOPICS.config, TOPICS.rules, TOPICS.profiles}
