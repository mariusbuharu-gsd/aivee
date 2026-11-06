"""Unit tests for MqttEdgeClient that never touch a broker."""

from datetime import UTC, datetime
from typing import Any

import pytest
from aivee_contracts.events import AlertEvent, DeviceStatus, Metrics, StaffSuggestion
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
        StaffSuggestion(suggestion_id="s", camera_id="c", track_id=1, staff_score=0.9, reason_ro="")
    )
    assert [(t, q) for t, _, q in sent] == [(edge.topics.metrics, 0), (edge.topics.suggestions, 1)]


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
