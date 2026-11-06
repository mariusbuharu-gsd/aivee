"""The API's MQTT link against the real Mosquitto config and ACL (testcontainers)."""

import asyncio
import contextlib
from typing import Any

import aiomqtt
import pytest
from aivee_api.edge.publisher import MqttEdgeLink
from aivee_api.metrics.cache import MetricsCache
from aivee_api.settings import ApiSettings
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
