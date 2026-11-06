"""The API's MQTT link against the real Mosquitto config and ACL (testcontainers)."""

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any

import aiomqtt
import pytest
from aivee_api.edge.live import LiveDetections
from aivee_api.edge.publisher import MqttEdgeLink
from aivee_api.edge.sync import MqttEdgeCommands, SuggestionDecision
from aivee_api.metrics.cache import MetricsCache
from aivee_api.settings import ApiSettings
from aivee_contracts.commands import EdgeCommand
from aivee_contracts.detections import Detections
from aivee_contracts.events import Metrics
from aivee_contracts.topics import Topics

pytestmark = pytest.mark.integration


async def test_retained_state_reaches_the_edge_and_metrics_come_back(
    broker: Any, site: str
) -> None:
    settings = ApiSettings(
        site=site,
        mqtt_host=broker.host,
        mqtt_port=broker.port,
        mqtt_api_user=broker.api[0],
        mqtt_api_password=broker.api[1],
    )
    device = broker.edge[0]
    topics = Topics(site=site, device=device)
    cache = MetricsCache()
    connected = asyncio.Event()

    async def on_connect() -> None:
        connected.set()

    link = MqttEdgeLink(settings, cache, on_connect=on_connect)
    task = asyncio.create_task(link.run())
    try:
        await asyncio.wait_for(connected.wait(), 10)
        await link.publish(topics.rules, b'{"device":"edge-01","rules":[]}', qos=1, retain=True)

        # The edge connects later and still gets the retained rule set (ACL: read own rules).
        async with aiomqtt.Client(
            broker.host,
            broker.port,
            username=broker.edge[0],
            password=broker.edge[1],
            identifier=f"edge-{site}",
        ) as edge:
            await edge.subscribe(topics.rules, qos=1)
            msg = await asyncio.wait_for(anext(aiter(edge.messages)), 5)
            assert msg.retain and msg.payload == b'{"device":"edge-01","rules":[]}'

            metrics = Metrics(device=device, fps=8.0, verified_ratio=0.2, cpu_percent=33)
            for _ in range(20):
                await edge.publish(topics.metrics, metrics.model_dump_json(), qos=0)
                await asyncio.sleep(0.2)
                if cache.latest():
                    break
        [sample] = cache.latest()
        assert (sample.site, sample.metrics.device, sample.metrics.fps) == (site, device, 8.0)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_commands_reach_the_edge_and_detections_come_back(broker: Any, site: str) -> None:
    settings = ApiSettings(
        site=site,
        mqtt_host=broker.host,
        mqtt_port=broker.port,
        mqtt_api_user=broker.api[0],
        mqtt_api_password=broker.api[1],
    )
    device = broker.edge[0]
    topics = Topics(site=site, device=device)
    live = LiveDetections()
    connected = asyncio.Event()

    async def on_connect() -> None:
        connected.set()

    link = MqttEdgeLink(settings, MetricsCache(), on_connect=on_connect, live=live)
    task = asyncio.create_task(link.run())
    try:
        await asyncio.wait_for(connected.wait(), 10)
        async with aiomqtt.Client(
            broker.host,
            broker.port,
            username=broker.edge[0],
            password=broker.edge[1],
            identifier=f"edge-{site}",
        ) as edge:
            await edge.subscribe(topics.commands, qos=1)
            commands = MqttEdgeCommands(link, site, device)
            await commands.suggestion_decided(SuggestionDecision("s1", "cam1", 7, True, device))
            msg = await asyncio.wait_for(anext(aiter(edge.messages)), 5)
            command = EdgeCommand.model_validate_json(msg.payload)  # type: ignore[arg-type]
            assert (command.kind, command.track_id, msg.retain) == ("confirm_staff", 7, False)

            detections = Detections(camera_id="cam1", ts=datetime.now(UTC))
            with live.subscribe() as queue:
                for _ in range(20):
                    await edge.publish(topics.detections, detections.model_dump_json(), qos=0)
                    with contextlib.suppress(TimeoutError):
                        got = await asyncio.wait_for(queue.get(), 0.25)
                        break
                else:
                    pytest.fail("no detections reached the API")
            assert (got.type, got.camera_id, got.data) == ("detections", "cam1", [])
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
