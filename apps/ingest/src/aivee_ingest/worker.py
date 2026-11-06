"""MQTT loop: subscribe, hand each message to IngestHandler, reconnect on failure."""

import asyncio
import logging
import socket

import aiomqtt
from aivee_contracts.topics import Topics

from aivee_ingest.config import IngestSettings
from aivee_ingest.handler import IngestHandler

log = logging.getLogger(__name__)

_ANY = Topics(site="+", device="+")
SUBSCRIPTIONS: list[tuple[str, int]] = [
    (Topics.shared_events(), 1),  # split between ingest replicas
    (_ANY.status, 1),
    (_ANY.suggestions, 1),  # every replica sees these; inserts are idempotent
    (_ANY.snapshot("+"), 1),  # every replica stores the file, so whoever gets the event has it
    (_ANY.metrics, 0),
]


def _payload_bytes(payload: object) -> bytes:
    if isinstance(payload, bytes | bytearray):
        return bytes(payload)
    return str(payload).encode() if payload is not None else b""


async def run_worker(
    settings: IngestSettings,
    handler: IngestHandler,
    ready: asyncio.Event | None = None,
    max_backoff_s: float = 30.0,
) -> None:
    """Run until cancelled. Each (re)connect re-subscribes; backoff grows to `max_backoff_s`."""
    client_id = settings.mqtt_client_id or f"ingest-{socket.gethostname()}"
    backoff = 1.0
    while True:
        try:
            async with aiomqtt.Client(
                hostname=settings.mqtt_host,
                port=settings.mqtt_port,
                username=settings.mqtt_ingest_user,
                password=settings.mqtt_ingest_password,
                identifier=client_id,
                protocol=aiomqtt.ProtocolVersion.V5,
            ) as client:
                await client.subscribe(SUBSCRIPTIONS)
                log.info("ingest %s subscribed to %d topics", client_id, len(SUBSCRIPTIONS))
                backoff = 1.0
                if ready is not None:
                    ready.set()
                async for message in client.messages:
                    try:
                        await handler.handle(str(message.topic), _payload_bytes(message.payload))
                    except Exception:
                        log.exception("failed to handle message on %s", message.topic)
        except aiomqtt.MqttError as e:
            if ready is not None:
                ready.clear()
            log.warning("MQTT connection lost (%s); reconnecting in %.0fs", e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff_s)
