"""`mqtt-frames://` source with a fake MQTT client: subscribe, decode, keep only the newest."""

import threading
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
import pytest
from aivee_edge.adapters.mqtt_frames import MqttFrameSource, camera_of, is_frames_source


@dataclass
class Msg:
    payload: bytes


class FakeClient:
    def __init__(self) -> None:
        self.on_connect: Any = None
        self.on_message: Any = None
        self.subscribed: list[tuple[str, int]] = []
        self.stopped = False

    def connect_async(self, host: str, port: int, keepalive: int = 60) -> None:
        self.on_connect(self, None, {}, 0, None)

    def loop_start(self) -> None: ...

    def subscribe(self, topic: str, qos: int = 0) -> None:
        self.subscribed.append((topic, qos))

    def deliver(self, payload: bytes) -> None:
        self.on_message(self, None, Msg(payload))

    def disconnect(self) -> None: ...

    def loop_stop(self) -> None:
        self.stopped = True


def jpeg(brightness: int, size: tuple[int, int] = (64, 48)) -> bytes:
    w, h = size
    ok, buf = cv2.imencode(".jpg", np.full((h, w, 3), brightness, dtype=np.uint8))
    assert ok
    return buf.tobytes()


TOPIC = "aivee/demo/vision-01/frames/cam-coleg-1"


@pytest.fixture
def setup() -> tuple[FakeClient, MqttFrameSource, list[float]]:
    client = FakeClient()
    now = [10.0]
    source = MqttFrameSource(client, TOPIC, clock=lambda: now[0], poll_s=0.05)
    source.start("mosquitto", 1883)
    return client, source, now


def test_source_url_names_the_camera() -> None:
    assert is_frames_source("mqtt-frames://cam-coleg-1")
    assert not is_frames_source("rtsp://mediamtx:8554/cam-01")
    assert camera_of("mqtt-frames://cam-coleg-1") == "cam-coleg-1"
    for bad in ("mqtt-frames://", "mqtt-frames://a/b", "rtsp://x"):
        with pytest.raises(ValueError):
            camera_of(bad)


def test_subscribes_to_the_frames_topic_at_qos_0(setup: Any) -> None:
    client, _, _ = setup
    assert client.subscribed == [(TOPIC, 0)]


def test_yields_decoded_frames_stamped_with_receive_time(setup: Any) -> None:
    client, source, now = setup
    client.deliver(jpeg(200))
    now[0] = 99.0  # reading later does not change the frame's time
    ts, image = source.read()
    assert ts == 10.0
    assert image.shape == (48, 64, 3) and abs(int(image.mean()) - 200) < 3


def test_keeps_only_the_newest_frame_when_the_pipeline_is_slow(setup: Any) -> None:
    client, source, now = setup
    for i, b in enumerate((50, 120, 220)):
        now[0] = 10.0 + i
        client.deliver(jpeg(b))
    ts, image = source.read()
    assert ts == 12.0 and abs(int(image.mean()) - 220) < 3
    assert source.dropped == 2


def test_skips_undecodable_payloads(setup: Any) -> None:
    client, source, _ = setup
    client.deliver(b"\xff\xd8\xff not really a jpeg")
    threading.Timer(0.05, client.deliver, args=(jpeg(80),)).start()
    _, image = source.read()
    assert abs(int(image.mean()) - 80) < 3


def test_read_blocks_until_a_frame_and_returns_none_after_close(setup: Any) -> None:
    client, source, _ = setup
    threading.Timer(0.05, client.deliver, args=(jpeg(30),)).start()
    assert source.read() is not None
    threading.Timer(0.05, source.close).start()
    assert source.read() is None
    assert client.stopped


def test_rotation_applies(setup: Any) -> None:
    client = FakeClient()
    source = MqttFrameSource(client, TOPIC, rotate=90)
    source.start("h", 1)
    client.deliver(jpeg(100, size=(64, 48)))
    _, image = source.read()
    assert image.shape == (64, 48, 3)
