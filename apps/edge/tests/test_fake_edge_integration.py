"""The fake edge's unattended scenario against a real Mosquitto with the production ACL."""

import threading
import time
from typing import Any

import paho.mqtt.client as mqtt
import pytest
from aivee_contracts.events import AlertEvent
from aivee_contracts.topics import Topics
from aivee_edge.adapters.mqtt import MqttEdgeClient
from paho.mqtt.enums import CallbackAPIVersion

from .test_fake_edge import fake_edge

pytestmark = pytest.mark.integration


def test_unattended_scenario_publishes_alert_events(broker: Any, site: str) -> None:
    device = broker.edge[0]
    topics = Topics(site=site, device=device)
    received: list[AlertEvent] = []
    done = threading.Event()
    subscribed = threading.Event()

    def on_message(_c: Any, _u: Any, msg: mqtt.MQTTMessage) -> None:
        received.append(AlertEvent.model_validate_json(msg.payload))
        if len(received) == 3:
            done.set()

    watcher = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    watcher.username_pw_set(*broker.api)
    watcher.on_message = on_message
    watcher.on_subscribe = lambda *_: subscribed.set()
    watcher.connect(broker.host, broker.port)
    watcher.subscribe(topics.events, qos=1)
    watcher.loop_start()
    assert subscribed.wait(5)

    edge = MqttEdgeClient(broker.host, broker.port, device, broker.edge[1], site, device)
    edge.start()
    try:
        rec = fake_edge.run_scenario(
            fake_edge.SCENARIOS["unattended"],
            edge,
            fake_edge.FallbackConfig(edge, "cam-01", force_demo=False),
            device=device,
            camera_id="cam-01",
            speed=500,
        )
        assert done.wait(10), received
    finally:
        time.sleep(0.2)
        edge.stop()
        watcher.loop_stop()
        watcher.disconnect()

    assert [(e.state, e.rule_id, e.zone_id) for e in received] == [
        ("opened", "demo-unattended", "masa-1"),
        ("arrived", "demo-unattended", "masa-1"),
        ("closed", "demo-unattended", "masa-1"),
    ]
    assert [e.event_id for e in received] == [e.event_id for e in rec.alerts]
