"""Everything the API sends to an edge device goes through the `EdgePublisher` port.

The edge only ever receives complete, retained documents (RuleSet, DeviceConfig,
StaffProfiles), so a device that reconnects gets the current state from the broker.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

import aiomqtt
from aivee_contracts.events import Metrics
from aivee_contracts.topics import Topics
from pydantic import ValidationError

from aivee_api.metrics.cache import MetricsCache
from aivee_api.settings import ApiSettings

log = logging.getLogger(__name__)


class PublisherUnavailable(RuntimeError):
    """The broker is not reachable right now; state is re-published on reconnect."""


class EdgePublisher(Protocol):
    async def publish(self, topic: str, payload: bytes, *, qos: int, retain: bool) -> None: ...


@dataclass
class Published:
    topic: str
    payload: bytes
    qos: int
    retain: bool


class RecordingPublisher:
    """In-memory publisher for tests and for running the API without a broker."""

    def __init__(self) -> None:
        self.messages: list[Published] = []

    async def publish(self, topic: str, payload: bytes, *, qos: int, retain: bool) -> None:
        self.messages.append(Published(topic, payload, qos, retain))

    def last(self, topic: str) -> Published | None:
        return next((m for m in reversed(self.messages) if m.topic == topic), None)


class MqttEdgeLink:
    """One long-lived aiomqtt connection: publishes retained state and caches metrics.

    `run()` reconnects with backoff; after every (re)connect it calls `on_connect`, which the
    app uses to re-publish the complete state (the broker may have lost retained messages).
    """

    def __init__(
        self,
        settings: ApiSettings,
        metrics: MetricsCache,
        on_connect: Callable[[], Awaitable[None]] | None = None,
        max_backoff_s: float = 30.0,
    ) -> None:
        self._settings = settings
        self._metrics = metrics
        self.on_connect = on_connect
        self._max_backoff_s = max_backoff_s
        self._client: aiomqtt.Client | None = None
        self.connected = asyncio.Event()

    async def publish(self, topic: str, payload: bytes, *, qos: int, retain: bool) -> None:
        client = self._client
        if client is None:
            raise PublisherUnavailable("MQTT broker not connected")
        try:
            await client.publish(topic, payload, qos=qos, retain=retain)
        except aiomqtt.MqttError as e:
            raise PublisherUnavailable(str(e)) from e

    async def run(self) -> None:
        s = self._settings
        backoff = 1.0
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=s.mqtt_host,
                    port=s.mqtt_port,
                    username=s.mqtt_api_user,
                    password=s.mqtt_api_password,
                    identifier=f"api-{s.site}",
                    protocol=aiomqtt.ProtocolVersion.V5,
                ) as client:
                    await client.subscribe(Topics.any_device("metrics"), qos=0)
                    self._client = client
                    self.connected.set()
                    backoff = 1.0
                    log.info("API connected to MQTT %s:%d", s.mqtt_host, s.mqtt_port)
                    if self.on_connect is not None:
                        try:
                            await self.on_connect()
                        except Exception:
                            log.exception("re-publishing edge state failed")
                    async for message in client.messages:
                        self._on_metrics(str(message.topic), message.payload)
            except aiomqtt.MqttError as e:
                log.warning("MQTT connection lost (%s); reconnecting in %.0fs", e, backoff)
            finally:
                self._client = None
                self.connected.clear()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self._max_backoff_s)

    def _on_metrics(self, topic: str, payload: object) -> None:
        parts = topic.split("/")
        if len(parts) != 4:
            return
        raw = payload if isinstance(payload, bytes | bytearray) else str(payload).encode()
        try:
            metrics = Metrics.model_validate_json(raw)
        except ValidationError:
            log.warning("invalid metrics on %s", topic)
            return
        # The topic (enforced by the broker ACL) is the source of truth for the device id.
        self._metrics.put(parts[1], metrics.model_copy(update={"device": parts[2]}))
