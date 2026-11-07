"""Frame source for cloud mode over HTTPS: `SOURCE=mqtt-frames://{camera_id}`.

The connector POSTs JPEGs to the API, which relays each to `Topics.frames(camera_id)` of the
device serving the camera (QoS 0, not retained). This source subscribes with the worker's own
MQTT identity (the ACL lets a device read `aivee/+/<its user>/frames/#`), keeps only the
newest frame (a slow pipeline drops frames instead of falling behind) and decodes it with cv2.

Timestamps are the receive time (`time.monotonic()`), so a pause in the upload shows up as a
gap between frames and the pipeline's existing stream-gap handling applies.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np
import paho.mqtt.client as mqtt
from aivee_contracts.topics import Topics
from paho.mqtt.enums import CallbackAPIVersion

from aivee_edge.adapters.capture import Image, rotate, rotate_check

log = logging.getLogger(__name__)

SCHEME = "mqtt-frames://"


def is_frames_source(source: str) -> bool:
    return source.startswith(SCHEME)


def camera_of(source: str) -> str:
    camera_id = source.removeprefix(SCHEME).strip("/")
    if not is_frames_source(source) or not camera_id or "/" in camera_id:
        raise ValueError(f"expected {SCHEME}<camera_id>, got {source!r}")
    return camera_id


def decode_jpeg(data: bytes) -> Image | None:
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return None if image is None else image


class MqttFrameSource:
    """`FrameSource` fed by an MQTT subscription. `client` is a paho-style client (a fake in
    tests); this class sets its callbacks, subscribes on every connect and owns its loop."""

    def __init__(
        self,
        client: Any,
        topic: str,
        *,
        rotate: int = 0,
        clock: Callable[[], float] = time.monotonic,
        decode: Callable[[bytes], Image | None] = decode_jpeg,
        poll_s: float = 1.0,
    ) -> None:
        rotate_check(rotate)
        self._client = client
        self.topic = topic
        self._rotate = rotate
        self._clock = clock
        self._decode = decode
        self._poll_s = poll_s
        self._cond = threading.Condition()
        self._newest: tuple[float, bytes] | None = None
        self._closed = False
        self.dropped = 0
        client.on_connect = self._on_connect
        client.on_message = self._on_message

    def start(self, host: str, port: int) -> None:
        self._client.connect_async(host, port, keepalive=30)
        self._client.loop_start()

    def _on_connect(self, client: Any, *_: Any) -> None:
        client.subscribe(self.topic, qos=0)
        log.info("frames subscribed topic=%s", self.topic)

    def _on_message(self, _client: Any, _userdata: Any, message: Any) -> None:
        with self._cond:
            if self._newest is not None:
                self.dropped += 1  # the pipeline has not taken the previous one yet
            self._newest = (self._clock(), bytes(message.payload))
            self._cond.notify()

    def read(self) -> tuple[float, Image] | None:
        """Block until the next frame arrives; None only after `close()`."""
        while True:
            with self._cond:
                while self._newest is None and not self._closed:
                    self._cond.wait(self._poll_s)
                if self._closed:
                    return None
                assert self._newest is not None
                ts, data = self._newest
                self._newest = None
            image = self._decode(data)
            if image is None:
                log.warning("frames: undecodable JPEG on %s (%d bytes)", self.topic, len(data))
                continue
            return ts, rotate(image, self._rotate)

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()
        self._client.disconnect()
        self._client.loop_stop()


def open_frames_source(
    source: str,
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    site: str,
    device: str,
    rotate: int = 0,
) -> MqttFrameSource:
    """Connect a frames subscriber for `mqtt-frames://<camera>` as this worker's device."""
    camera_id = camera_of(source)
    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=f"frames-{site}-{user}-{camera_id}",
        protocol=mqtt.MQTTv5,
    )
    client.username_pw_set(user, password)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    frames = MqttFrameSource(
        client, Topics(site=site, device=device).frames(camera_id), rotate=rotate
    )
    frames.start(host, port)
    return frames
