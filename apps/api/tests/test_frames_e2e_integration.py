"""Frames over HTTPS end to end on the real Mosquitto config and ACL (testcontainers):
connector POST → API → MQTT → the vision worker's `mqtt-frames://` source, plus MJPEG out.
Prints the measured latencies (run with `-s` to see them)."""

import asyncio
import base64
import statistics
import time
from typing import Any

import cv2
import httpx
import numpy as np
import pytest
from aivee_api.edge.publisher import MqttEdgeLink
from aivee_api.frames.router import get_camera_topics
from aivee_api.frames.store import LiveFrames, mjpeg_stream
from aivee_api.main import create_app
from aivee_api.metrics.cache import MetricsCache
from aivee_api.settings import ApiSettings
from aivee_contracts.topics import Topics
from aivee_edge.adapters.mqtt_frames import open_frames_source

pytestmark = pytest.mark.integration


def _jpeg(i: int) -> bytes:
    image = np.full((360, 640, 3), (i * 37) % 256, dtype=np.uint8)
    cv2.putText(image, str(i), (40, 200), cv2.FONT_HERSHEY_SIMPLEX, 4, (255, 255, 255), 6)
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
    assert ok
    return buf.tobytes()


async def test_posted_frames_reach_the_vision_worker_and_the_mjpeg_stream(
    broker: Any, site: str, translator: Any, services_factory: Any, tmp_path: Any
) -> None:
    settings = ApiSettings(
        site=site,
        mqtt_host=broker.host,
        mqtt_port=broker.port,
        mqtt_api_user=broker.api[0],
        mqtt_api_password=broker.api[1],
        snapshot_dir=tmp_path,
        stream_publish_user="pub",
        stream_publish_password="s3cret",
    )
    device = broker.edge[0]
    link = MqttEdgeLink(settings, MetricsCache())
    link_task = asyncio.create_task(link.run())
    svc = services_factory(settings, None, link, translator)
    svc.frames = LiveFrames(link)
    app = create_app(svc)

    async def find(camera_id: str) -> Topics | None:
        return Topics(site=site, device=device)

    app.dependency_overrides[get_camera_topics] = lambda: find
    worker = open_frames_source(
        "mqtt-frames://cam-e2e",
        host=broker.host,
        port=broker.port,
        user=device,
        password=broker.edge[1],
        site=site,
        device=device,
    )
    # Another device may not read this worker's frames (ACL %u).
    stranger = open_frames_source(
        "mqtt-frames://cam-e2e",
        host=broker.host,
        port=broker.port,
        user=broker.upload[0],
        password=broker.upload[1],
        site=site,
        device=device,
    )
    auth = {"Authorization": "Basic " + base64.b64encode(b"pub:s3cret").decode()}
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    try:
        await asyncio.wait_for(link.connected.wait(), 10)
        await asyncio.sleep(1.0)  # let both subscriptions land

        async def no() -> bool:
            return False

        stream = mjpeg_stream(svc.frames, "cam-e2e", fps=1000, disconnected=no)
        to_worker: list[float] = []
        to_mjpeg: list[float] = []
        for i in range(20):
            frame = _jpeg(i)
            next_part = asyncio.ensure_future(anext(stream))
            started = time.perf_counter()
            r = await client.post("/api/ingest/frames/cam-e2e", content=frame, headers=auth)
            assert r.status_code == 204, r.text
            part = await asyncio.wait_for(next_part, 5)
            to_mjpeg.append(time.perf_counter() - started)
            item = await asyncio.wait_for(asyncio.to_thread(worker.read), 5)
            to_worker.append(time.perf_counter() - started)
            assert item is not None and frame in part
            assert item[1].shape == (360, 640, 3)
            await asyncio.sleep(0.2)  # 5 fps

        assert stranger._newest is None
        ms = lambda xs: statistics.median(xs) * 1000  # noqa: E731
        print(
            f"\nframes e2e localhost: POST→worker median {ms(to_worker):.1f} ms "
            f"(max {max(to_worker) * 1000:.1f}), POST→MJPEG median {ms(to_mjpeg):.1f} ms"
        )
        assert ms(to_worker) < 500
    finally:
        await client.aclose()
        worker.close()
        stranger.close()
        link_task.cancel()
