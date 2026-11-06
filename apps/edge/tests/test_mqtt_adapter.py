"""Unit tests for MqttEdgeClient that never touch a broker."""

from datetime import UTC, datetime
from typing import Any

import pytest
from aivee_contracts.commands import EdgeCommand
from aivee_contracts.detections import Detections
from aivee_contracts.events import AlertEvent, DeviceStatus, Metrics, StaffSuggestion
from aivee_contracts.geometry import CameraConfig, DeviceConfig, Zone
from aivee_contracts.rules import RuleSet
from aivee_edge.adapters.mqtt import MqttEdgeClient


class _Info:
    def wait_for_publish(self, timeout: float | None = None) -> None:
        return None


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> tuple[MqttEdgeClient, list[tuple[str, Any, int]]]:
    edge = MqttEdgeClient("localhost", 1883, "edge-01", "pw", "s1", "edge-01")
    sent: list[tuple[str, Any, int]] = []

    def fake_publish(topic: str, payload: Any = None, qos: int = 0, retain: bool = False) -> _Info:
        sent.append((topic, payload, qos))
        return _Info()

    monkeypatch.setattr(edge._client, "publish", fake_publish)
    return edge, sent


def _event() -> AlertEvent:
    return AlertEvent(
        event_id="e1",
        rule_id="r1",
        camera_id="cam1",
        zone_id="t1",
        state="opened",
        at=datetime.now(UTC),
        summary_ro="Masa 1 așteaptă",
    )


def test_snapshot_is_published_before_its_event(client: Any) -> None:
    edge, sent = client
    edge.publish_alert(_event(), b"\xff\xd8jpeg")
    assert [t for t, _, _ in sent] == [edge.topics.snapshot("e1"), edge.topics.events]
    assert all(qos == 1 for _, _, qos in sent)
    assert AlertEvent.model_validate_json(sent[1][1]).snapshot is True


def test_alert_without_snapshot_publishes_only_the_event(client: Any) -> None:
    edge, sent = client
    edge.publish_alert(_event(), None)
    assert [(t, q) for t, _, q in sent] == [(edge.topics.events, 1)]


def test_metrics_are_qos0_and_suggestions_qos1(client: Any) -> None:
    edge, sent = client
    edge.publish_metrics(Metrics(device="edge-01", fps=10, verified_ratio=0.1, cpu_percent=50))
    edge.publish_suggestion(
        StaffSuggestion(
            suggestion_id="s", camera_id="c", track_id=1, staff_score=0.9, reason_ro=""
        ),
        None,
    )
    assert [(t, q) for t, _, q in sent] == [(edge.topics.metrics, 0), (edge.topics.suggestions, 1)]
    assert StaffSuggestion.model_validate_json(sent[1][1]).snapshot is False


def test_detections_are_qos0_and_not_retained(monkeypatch: pytest.MonkeyPatch) -> None:
    edge = MqttEdgeClient("localhost", 1883, "edge-01", "pw", "s1", "edge-01")
    sent: list[tuple[str, Any, int, bool]] = []

    def fake_publish(topic: str, payload: Any = None, qos: int = 0, retain: bool = False) -> _Info:
        sent.append((topic, payload, qos, retain))
        return _Info()

    monkeypatch.setattr(edge._client, "publish", fake_publish)
    detections = Detections(camera_id="cam-01", ts=datetime.now(UTC))
    edge.publish_detections(detections)
    [(topic, payload, qos, retain)] = sent
    assert (topic, qos, retain) == (edge.topics.detections, 0, False)
    assert Detections.model_validate_json(payload) == detections


def test_suggestion_crop_is_published_before_the_suggestion(client: Any) -> None:
    edge, sent = client
    suggestion = StaffSuggestion(
        suggestion_id="s9", camera_id="c", track_id=1, staff_score=0.9, reason_ro=""
    )
    edge.publish_suggestion(suggestion, b"\xff\xd8crop")
    assert [(t, q) for t, _, q in sent] == [
        (edge.topics.snapshot("s9"), 1),
        (edge.topics.suggestions, 1),
    ]
    assert sent[0][1] == b"\xff\xd8crop"
    assert StaffSuggestion.model_validate_json(sent[1][1]).snapshot is True


def test_last_will_is_retained_offline_status() -> None:
    edge = MqttEdgeClient("localhost", 1883, "edge-01", "pw", "s1", "edge-01")
    will = edge._client._will_topic.decode(), edge._client._will_payload
    assert will[0] == edge.topics.status
    assert DeviceStatus.model_validate_json(will[1]).state == "offline"
    assert edge._client._will_retain is True and edge._client._will_qos == 1


def test_rules_are_empty_until_retained_ruleset_arrives() -> None:
    edge = MqttEdgeClient("localhost", 1883, "edge-01", "pw", "s1", "edge-01")
    assert edge.rules() == []
    with pytest.raises(LookupError):
        edge.camera()

    class Msg:
        topic = edge.topics.rules
        payload = RuleSet(device="edge-01", rules=[]).model_dump_json().encode()

    edge._on_message(edge._client, None, Msg())  # type: ignore[arg-type]
    assert edge.rules() == []
    Msg.payload = b"not json"
    edge._on_message(edge._client, None, Msg())  # type: ignore[arg-type]  # ignored, no raise


def _config_msg(edge: MqttEdgeClient, config: DeviceConfig | bytes) -> Any:
    class Msg:
        topic = edge.topics.config
        payload = config if isinstance(config, bytes) else config.model_dump_json().encode()

    return Msg()


def _cam(cam_id: str) -> CameraConfig:
    zone = Zone(id="t1", name="Masa 1", tag="table", polygon=[(0, 0), (1, 0), (1, 1)])
    return CameraConfig(id=cam_id, name=cam_id, source="0", zones=[zone])


def test_retained_device_config_selects_this_camera() -> None:
    edge = MqttEdgeClient("localhost", 1883, "u", "pw", "s1", "edge-01", camera_id="cam-02")
    assert edge.device_config() is None
    config = DeviceConfig(device="edge-01", cameras=[_cam("cam-01"), _cam("cam-02")])
    edge._on_message(edge._client, None, _config_msg(edge, config))
    assert edge.device_config() == config
    assert edge.camera().id == "cam-02"
    assert [z.name for z in edge.camera().zones] == ["Masa 1"]


def test_device_config_without_camera_id_uses_first_and_falls_back() -> None:
    fallback = _cam("local")
    edge = MqttEdgeClient("localhost", 1883, "u", "pw", "s1", "edge-01", camera=fallback)
    assert edge.camera() == fallback
    other = DeviceConfig(device="edge-01", cameras=[_cam("cam-09")])
    edge._on_message(edge._client, None, _config_msg(edge, other))
    assert edge.camera() == fallback  # camera_id "local" is not in the config

    edge = MqttEdgeClient("localhost", 1883, "u", "pw", "s1", "edge-01")
    edge._on_message(edge._client, None, _config_msg(edge, other))
    assert edge.camera().id == "cam-09"
    edge._on_message(edge._client, None, _config_msg(edge, b"{bad"))  # ignored
    assert edge.camera().id == "cam-09"


def test_subscribes_to_config_on_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    edge = MqttEdgeClient("localhost", 1883, "u", "pw", "s1", "edge-01")
    subs: list[Any] = []
    monkeypatch.setattr(edge._client, "subscribe", lambda topics: subs.append(topics))
    monkeypatch.setattr(edge._client, "publish", lambda *a, **k: _Info())

    class Ok:
        is_failure = False

    edge._on_connect(edge._client, None, None, Ok(), None)  # type: ignore[arg-type]
    assert edge.topics.config in [t for t, _ in subs[0]]
    assert (edge.topics.commands, 1) in subs[0]


def _command_msg(edge: MqttEdgeClient, payload: bytes) -> Any:
    class Msg:
        topic = edge.topics.commands

    Msg.payload = payload  # type: ignore[attr-defined]
    return Msg()


def test_commands_are_queued_until_the_pipeline_takes_them() -> None:
    edge = MqttEdgeClient("localhost", 1883, "u", "pw", "s1", "edge-01")
    cmd = EdgeCommand(
        command_id="c1",
        kind="confirm_staff",
        camera_id="cam-01",
        track_id=7,
        suggestion_id="s1",
        at=datetime.now(UTC),
    )
    assert edge.take_commands() == []
    edge._on_message(edge._client, None, _command_msg(edge, cmd.model_dump_json().encode()))
    edge._on_message(edge._client, None, _command_msg(edge, b"{bad"))  # ignored
    assert edge.take_commands() == [cmd]
    assert edge.take_commands() == []
