"""The API's edge seam without a broker or a database: commands out, live detections in."""

import json
import time
from datetime import UTC, datetime
from typing import Any

import pytest
from aivee_api.deps import Services
from aivee_api.edge.live import LiveDetections
from aivee_api.edge.publisher import MqttEdgeLink, PublisherUnavailable, RecordingPublisher
from aivee_api.edge.sync import MqttEdgeCommands, SuggestionDecision
from aivee_api.events import router as events_router
from aivee_api.events.schemas import DetectionsMessage
from aivee_api.main import create_app
from aivee_api.metrics.cache import MetricsCache
from aivee_api.settings import ApiSettings
from aivee_contracts.commands import EdgeCommand
from aivee_contracts.detections import Detections
from aivee_contracts.topics import Topics
from fastapi.testclient import TestClient
from pydantic import BaseModel

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def _commands(publisher: Any) -> MqttEdgeCommands:
    return MqttEdgeCommands(publisher, "demo", "edge-01", clock=lambda: NOW, new_id=lambda: "c1")


async def test_decision_is_sent_to_the_suggesting_device_as_an_edge_command() -> None:
    publisher = RecordingPublisher()
    await _commands(publisher).suggestion_decided(
        SuggestionDecision("s1", "cam-01", 7, confirmed=True, device_id="edge-02")
    )
    [msg] = publisher.messages
    assert msg.topic == Topics(site="demo", device="edge-02").commands
    assert (msg.qos, msg.retain) == (1, False)
    assert EdgeCommand.model_validate_json(msg.payload) == EdgeCommand(
        command_id="c1",
        kind="confirm_staff",
        camera_id="cam-01",
        track_id=7,
        suggestion_id="s1",
        at=NOW,
    )


async def test_reject_without_device_goes_to_the_default_device() -> None:
    publisher = RecordingPublisher()
    await _commands(publisher).suggestion_decided(
        SuggestionDecision("s2", "cam-01", 3, confirmed=False)
    )
    [msg] = publisher.messages
    assert msg.topic == Topics(site="demo", device="edge-01").commands
    assert EdgeCommand.model_validate_json(msg.payload).kind == "reject_staff"


async def test_command_is_dropped_not_raised_when_the_broker_is_down() -> None:
    class Down:
        async def publish(self, topic: str, payload: bytes, *, qos: int, retain: bool) -> None:
            raise PublisherUnavailable("down")

    await _commands(Down()).suggestion_decided(SuggestionDecision("s3", "cam-01", 1, True))


def _detections() -> Detections:
    return Detections.model_validate(
        {
            "camera_id": "cam-01",
            "ts": NOW,
            "tracks": [
                {
                    "track_id": 4,
                    "bbox": [0.1, 0.2, 0.4, 0.8],
                    "role": "staff",
                    "staff_score": 0.9,
                    "raised_hand": False,
                }
            ],
            "objects": [{"label": "cup", "bbox": [0.5, 0.5, 0.6, 0.6]}],
        }
    )


def test_detections_message_matches_the_dashboard_shape() -> None:
    msg = DetectionsMessage.from_detections(_detections())
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "detections" and data["camera_id"] == "cam-01"
    [det] = data["data"]
    assert det["track_id"] == 4 and det["role"] == "staff"
    assert det["box"] == pytest.approx([0.1, 0.2, 0.3, 0.6])  # [x, y, width, height]


async def test_live_detections_fan_out_and_drop_the_oldest_when_a_reader_lags() -> None:
    live = LiveDetections(maxsize=2)
    msg = DetectionsMessage.from_detections(_detections())
    with live.subscribe() as a, live.subscribe() as b:
        assert live.subscribers == 2
        for i in range(3):
            live.publish(msg.model_copy(update={"camera_id": f"cam-{i}"}))
        assert [a.get_nowait().camera_id for _ in range(2)] == ["cam-1", "cam-2"]
        assert b.qsize() == 2
    assert live.subscribers == 0


def test_mqtt_link_forwards_detections_with_the_topic_device() -> None:
    live = LiveDetections()
    link = MqttEdgeLink(ApiSettings(), MetricsCache(), live=live)
    with live.subscribe() as q:
        link._on_message("aivee/demo/edge-01/detections", _detections().model_dump_json().encode())
        link._on_message("aivee/demo/edge-01/detections", b"not json")
        assert q.get_nowait().camera_id == "cam-01"
        assert q.empty()


class _NoFeed:
    def __init__(self, _sessions: Any, _locations: Any = None) -> None: ...

    async def start(self) -> None: ...

    async def poll(self) -> list[BaseModel]:
        return []


class _AllowAll:
    alert_locations: frozenset[str] = frozenset()

    async def refresh(self, _sessions: Any) -> None: ...

    def allows(self, _message: BaseModel) -> bool:
        return True


async def _allow_all(_ws: Any, _services: Any) -> _AllowAll:
    return _AllowAll()


def test_ws_events_pushes_live_detections(
    monkeypatch: pytest.MonkeyPatch, settings: ApiSettings, translator: Any, services_factory: Any
) -> None:
    monkeypatch.setattr(events_router, "LiveFeed", _NoFeed)
    monkeypatch.setattr(events_router, "AlertFeed", _NoFeed)
    monkeypatch.setattr(events_router, "authenticate_ws", _allow_all)
    services: Services = services_factory(settings, None, RecordingPublisher(), translator)
    app = create_app(services)
    msg = DetectionsMessage.from_detections(_detections())
    with TestClient(app) as client, client.websocket_connect("/ws/events") as ws:
        deadline = time.monotonic() + 5
        while services.live.subscribers == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert client.portal is not None
        client.portal.call(services.live.publish, msg)
        data = ws.receive_json()
    assert data["type"] == "detections" and data["camera_id"] == "cam-01"
    assert data["data"][0]["track_id"] == 4
