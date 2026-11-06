"""MqttEdgeClient against a real Mosquitto with the production ACL."""

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import paho.mqtt.client as mqtt
import pytest
from aivee_contracts.commands import EdgeCommand
from aivee_contracts.detections import Detections
from aivee_contracts.events import DeviceStatus
from aivee_contracts.rules import Action, Condition, Rule, RuleSet
from aivee_contracts.topics import Topics
from aivee_edge.adapters.mqtt import MqttEdgeClient
from paho.mqtt.enums import CallbackAPIVersion

pytestmark = pytest.mark.integration


def _wait(cond: Callable[[], bool], timeout: float = 10) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _api_client(broker: Any) -> mqtt.Client:
    c = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    c.username_pw_set(*broker.api)
    c.connect(broker.host, broker.port)
    c.loop_start()
    return c


def _edge(broker: Any, site: str) -> MqttEdgeClient:
    user, password = broker.edge
    edge = MqttEdgeClient(broker.host, broker.port, user, password, site, user, keepalive=5)
    edge.start()
    return edge


def _ruleset(device: str, rule_id: str) -> RuleSet:
    rule = Rule(
        id=rule_id,
        camera_id="cam1",
        name="Așteptare",
        prompt_ro="Anunță-mă dacă nimeni nu vine la masă",
        zone_tag="table",
        all_of=[Condition(kind="absent", role="staff", min_duration_s=60)],
        action=Action(type="telegram"),
    )
    return RuleSet(device=device, rules=[rule])


def test_retained_ruleset_reaches_a_fresh_client_after_reconnect(broker: Any, site: str) -> None:
    device = broker.edge[0]
    topics = Topics(site=site, device=device)
    api = _api_client(broker)
    api.publish(topics.rules, _ruleset(device, "r1").model_dump_json(), qos=1, retain=True)

    first = _edge(broker, site)
    assert _wait(lambda: [r.id for r in first.rules()] == ["r1"])
    first.stop()

    api.publish(
        topics.rules, _ruleset(device, "r2").model_dump_json(), qos=1, retain=True
    ).wait_for_publish(5)
    second = _edge(broker, site)
    try:
        assert _wait(lambda: [r.id for r in second.rules()] == ["r2"])
    finally:
        second.stop()
        api.loop_stop()
        api.disconnect()


def test_command_from_the_api_user_reaches_the_edge_through_the_acl(broker: Any, site: str) -> None:
    device = broker.edge[0]
    topics = Topics(site=site, device=device)
    edge = _edge(broker, site)
    api = _api_client(broker)
    cmd = EdgeCommand(
        command_id="c1",
        kind="confirm_staff",
        camera_id="cam1",
        track_id=7,
        suggestion_id="s1",
        at=datetime.now(UTC),
    )
    try:
        api.publish(topics.commands, cmd.model_dump_json(), qos=1).wait_for_publish(5)
        received: list[EdgeCommand] = []
        assert _wait(lambda: bool(received.extend(edge.take_commands()) or received))
        assert received == [cmd]
    finally:
        edge.stop()
        api.loop_stop()
        api.disconnect()


def test_acl_lets_the_edge_publish_its_own_detections(broker: Any, site: str) -> None:
    topics = Topics(site=site, device=broker.edge[0])
    got = threading.Event()
    watcher = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    watcher.username_pw_set(*broker.api)
    watcher.on_message = lambda *_: got.set()
    watcher.connect(broker.host, broker.port)
    watcher.subscribe(topics.detections, qos=0)
    watcher.loop_start()
    edge = _edge(broker, site)
    try:
        detections = Detections(camera_id="cam1", ts=datetime.now(UTC))
        for _ in range(20):
            edge.publish_detections(detections)
            if got.wait(0.25):
                break
        assert got.is_set()
    finally:
        edge.stop()
        watcher.loop_stop()
        watcher.disconnect()


def test_broker_publishes_offline_will_when_edge_dies(broker: Any, site: str) -> None:
    device = broker.edge[0]
    topics = Topics(site=site, device=device)
    seen: list[str] = []
    got = threading.Event()

    watcher = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    watcher.username_pw_set(*broker.api)

    def on_message(_c: Any, _u: Any, msg: mqtt.MQTTMessage) -> None:
        seen.append(DeviceStatus.model_validate_json(msg.payload).state)
        got.set()

    watcher.on_message = on_message
    watcher.connect(broker.host, broker.port)
    watcher.subscribe(topics.status, qos=1)
    watcher.loop_start()

    edge = _edge(broker, site)
    assert _wait(lambda: "online" in seen)
    # Die without DISCONNECT: stop the network loop and drop the socket.
    edge._client.loop_stop()
    sock = edge._client.socket()
    assert sock is not None
    sock.close()
    try:
        assert _wait(lambda: seen[-1:] == ["offline"])
    finally:
        watcher.loop_stop()
        watcher.disconnect()


def test_acl_blocks_edge_from_other_devices_topics(broker: Any, site: str) -> None:
    """An edge may only publish under its own device id; the broker drops the rest."""
    other = Topics(site=site, device="edge-99")
    received = threading.Event()

    watcher = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    watcher.username_pw_set(*broker.api)
    watcher.on_message = lambda *_: received.set()
    watcher.connect(broker.host, broker.port)
    watcher.subscribe(other.events, qos=1)
    watcher.loop_start()

    edge = _edge(broker, site)
    try:
        edge._client.publish(other.events, b"{}", qos=1)
        assert not received.wait(1.5)
    finally:
        edge.stop()
        watcher.loop_stop()
        watcher.disconnect()
