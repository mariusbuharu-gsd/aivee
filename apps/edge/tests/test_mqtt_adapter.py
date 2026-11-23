"""Unit tests for MqttEdgeClient that never touch a broker."""

from datetime import UTC, datetime
from typing import Any

import pytest
from aivee_contracts.commands import EdgeCommand
from aivee_contracts.detections import Detections
from aivee_contracts.events import (
    AlertEvent,
    DeviceStatus,
    Metrics,
    ObjectChange,
    StaffSuggestion,
)
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


def test_object_change_publishes_the_before_snapshot_too(client: Any) -> None:
    edge, sent = client
    event = _event().model_copy(update={"object_change": ObjectChange(objects=["cup"])})
    edge.publish_alert(event, b"after", b"before")
    assert [t for t, _, _ in sent] == [
        edge.topics.snapshot("e1"),
        edge.topics.snapshot_before("e1"),
        edge.topics.events,
    ]
    published = AlertEvent.model_validate_json(sent[2][1])
    assert published.snapshot is True
    assert published.object_change is not None and published.object_change.before_snapshot


def test_before_snapshot_is_ignored_without_an_object_change(client: Any) -> None:
    edge, sent = client
    edge.publish_alert(_event(), b"after", b"before")
    assert [t for t, _, _ in sent] == [edge.topics.snapshot("e1"), edge.topics.events]


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


# -- transport (remote edge over wss) ---------------------------------------------------------


def test_default_transport_is_plain_tcp_without_tls() -> None:
    edge = MqttEdgeClient("localhost", 1883, "edge-01", "pw", "s1", "edge-01")
    assert edge._client._transport == "tcp"
    assert edge._client._ssl_context is None


def test_websockets_transport_uses_the_given_path() -> None:
    edge = MqttEdgeClient(
        "mqtt.example.com",
        80,
        "edge-coleg-1",
        "pw",
        "s1",
        "edge-coleg-1",
        transport="websockets",
        ws_path="/broker",
    )
    assert edge._client._transport == "websockets"
    assert edge._client._websocket_path == "/broker"
    assert edge._client._ssl_context is None


def test_tls_sets_a_verifying_ssl_context() -> None:
    import ssl

    edge = MqttEdgeClient(
        "mqtt.example.com",
        443,
        "edge-coleg-1",
        "pw",
        "s1",
        "edge-coleg-1",
        transport="websockets",
        tls=True,
    )
    ctx = edge._client._ssl_context
    assert ctx is not None
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_unknown_transport_is_rejected() -> None:
    with pytest.raises(ValueError):
        MqttEdgeClient("h", 1, "u", "p", "s", "d", transport="carrier-pigeon")


# -- several cameras on one device client (V8) -------------------------------------------------


def _cmd(cmd_id: str, camera_id: str) -> bytes:
    return (
        EdgeCommand(
            command_id=cmd_id,
            kind="confirm_staff",
            camera_id=camera_id,
            track_id=7,
            suggestion_id="s1",
            at=datetime.now(UTC),
        )
        .model_dump_json()
        .encode()
    )


def _two_cameras() -> tuple[MqttEdgeClient, Any, Any]:
    edge = MqttEdgeClient("localhost", 1883, "u", "pw", "s1", "edge-01", metrics_interval_s=5)
    one = edge.for_camera(CameraConfig(id="cam-01", name="cam-01", source="rtsp://a"))
    two = edge.for_camera(CameraConfig(id="cam-02", name="cam-02", source="rtsp://b"))
    return edge, one, two


def test_each_camera_view_reads_its_own_camera_config() -> None:
    edge, one, two = _two_cameras()
    assert (one.camera().id, two.camera().id) == ("cam-01", "cam-02")  # fallbacks, no zones
    assert one.camera().zones == []
    config = DeviceConfig(device="edge-01", cameras=[_cam("cam-02"), _cam("cam-01")])
    edge._on_message(edge._client, None, _config_msg(edge, config))
    assert one.camera() == _cam("cam-01") and two.camera() == _cam("cam-02")


def test_commands_reach_the_pipeline_of_their_camera() -> None:
    edge, one, two = _two_cameras()
    for cmd_id, cam in [("c1", "cam-01"), ("c2", "cam-02"), ("c3", "cam-01"), ("c4", "cam-09")]:
        edge._on_message(edge._client, None, _command_msg(edge, _cmd(cmd_id, cam)))
    assert [c.command_id for c in two.take_commands()] == ["c2"]
    assert [c.command_id for c in one.take_commands()] == ["c1", "c3"]
    assert one.take_commands() == [] and two.take_commands() == []
    assert edge.take_commands() == []  # c4: no such camera on this device, dropped


def test_status_lists_every_camera_of_the_device() -> None:
    edge, _one, _two = _two_cameras()
    status = DeviceStatus.model_validate_json(edge._status("online"))
    assert status.cameras == ["cam-01", "cam-02"]
    will = DeviceStatus.model_validate_json(edge._client._will_payload)
    assert will.state == "offline" and will.cameras == ["cam-01", "cam-02"]


def test_camera_views_share_one_metrics_message_per_device(monkeypatch: pytest.MonkeyPatch) -> None:
    edge, one, two = _two_cameras()
    sent: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        edge._client, "publish", lambda t, p=None, qos=0, retain=False: sent.append((t, p))
    )
    edge._device_metrics._published_at -= 10  # type: ignore[union-attr]  # an interval ago
    one.publish_metrics(Metrics(device="edge-01", fps=10, verified_ratio=0.2, cpu_percent=50))
    assert sent == []  # waits for cam-02
    two.publish_metrics(Metrics(device="edge-01", fps=9, verified_ratio=0.4, cpu_percent=55))
    [(topic, payload)] = sent
    assert topic == edge.topics.metrics
    assert Metrics.model_validate_json(payload).fps == 9


def test_camera_views_publish_events_on_the_device_topics(client: Any) -> None:
    edge, sent = client
    view = edge.for_camera(CameraConfig(id="cam1", name="cam1", source="rtsp://a"))
    view.publish_alert(_event(), None)
    view.publish_detections(Detections(camera_id="cam1", ts=datetime.now(UTC)))
    assert [t for t, _, _ in sent] == [edge.topics.events, edge.topics.detections]


# -- per-camera stream health on the retained status -------------------------------------------


def _health(camera_id: str, state: str) -> Any:
    from aivee_contracts.events import CameraStreamHealth

    return CameraStreamHealth(
        camera_id=camera_id,
        state=state,  # type: ignore[arg-type]
        last_frame_at=datetime(2026, 11, 23, 12, 0, tzinfo=UTC),
        fps=15.0,
    )


def _retained(monkeypatch: pytest.MonkeyPatch, edge: MqttEdgeClient) -> list[tuple[str, Any, bool]]:
    sent: list[tuple[str, Any, bool]] = []

    def fake_publish(topic: str, payload: Any = None, qos: int = 0, retain: bool = False) -> _Info:
        sent.append((topic, payload, retain))
        return _Info()

    monkeypatch.setattr(edge._client, "publish", fake_publish)
    return sent


def test_camera_health_republishes_the_retained_online_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edge, _one, _two = _two_cameras()
    sent = _retained(monkeypatch, edge)
    edge.connected.set()
    edge.publish_camera_health([_health("cam-01", "ok"), _health("cam-02", "down")])
    [(topic, payload, retain)] = sent
    status = DeviceStatus.model_validate_json(payload)
    assert topic == edge.topics.status and retain is True
    assert status.state == "online" and status.cameras == ["cam-01", "cam-02"]
    assert [(h.camera_id, h.state) for h in status.camera_health] == [
        ("cam-01", "ok"),
        ("cam-02", "down"),
    ]


def test_camera_health_waits_for_the_connection_and_goes_out_on_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edge, _one, _two = _two_cameras()
    sent = _retained(monkeypatch, edge)
    monkeypatch.setattr(edge._client, "subscribe", lambda *_a, **_k: None)
    edge.publish_camera_health([_health("cam-02", "reconnecting")])
    assert sent == []  # not connected: the next connect carries it

    class Ok:
        is_failure = False

    edge._on_connect(edge._client, None, None, Ok(), None)  # type: ignore[arg-type]
    [(_topic, payload, _retain)] = sent
    assert DeviceStatus.model_validate_json(payload).camera_health[0].state == "reconnecting"


def test_offline_status_and_last_will_carry_no_camera_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edge, _one, _two = _two_cameras()
    sent = _retained(monkeypatch, edge)
    monkeypatch.setattr(edge._client, "disconnect", lambda *_a, **_k: None)
    monkeypatch.setattr(edge._client, "loop_stop", lambda *_a, **_k: None)
    edge.connected.set()
    edge.publish_camera_health([_health("cam-01", "ok")])
    edge.stop()
    offline = DeviceStatus.model_validate_json(sent[-1][1])
    assert offline.state == "offline" and offline.camera_health == []
    will = DeviceStatus.model_validate_json(edge._client._will_payload)
    assert will.state == "offline" and will.camera_health == []
