"""Routes that need no database: health, CORS, snapshots; plus the publisher and metrics cache."""

from typing import Any

import httpx
import pytest
from aivee_api.edge.publisher import MqttEdgeLink, PublisherUnavailable, RecordingPublisher
from aivee_api.edge.sync import EdgeSync
from aivee_api.main import create_app
from aivee_api.metrics.cache import MetricsCache
from aivee_api.settings import ApiSettings
from aivee_contracts.events import Metrics

JPEG = b"\xff\xd8\xff\xe0fake-jpeg\xff\xd9"


def _no_db() -> Any:
    raise AssertionError("this route must not touch the database")


@pytest.fixture
def client(
    settings: ApiSettings, publisher: RecordingPublisher, translator: Any, services_factory: Any
) -> httpx.AsyncClient:
    app = create_app(services_factory(settings, _no_db, publisher, translator))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_healthz(client: httpx.AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


async def test_cors_allows_the_dashboard(client: httpx.AsyncClient) -> None:
    r = await client.options(
        "/api/rules",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


async def test_snapshot_is_served_as_jpeg(client: httpx.AsyncClient, settings: ApiSettings) -> None:
    (settings.snapshot_dir / "ev-1.jpg").write_bytes(JPEG)
    r = await client.get("/api/snapshots/ev-1")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content == JPEG


@pytest.mark.parametrize("event_id", ["missing", "..%2F..%2Fetc%2Fpasswd", "a.b"])
async def test_snapshot_missing_or_unsafe_is_404(client: httpx.AsyncClient, event_id: str) -> None:
    r = await client.get(f"/api/snapshots/{event_id}")
    assert r.status_code == 404


async def test_publisher_without_broker_raises_unavailable(settings: ApiSettings) -> None:
    link = MqttEdgeLink(settings, MetricsCache())
    with pytest.raises(PublisherUnavailable):
        await link.publish("aivee/x/y/rules", b"{}", qos=1, retain=True)


async def test_sync_logs_instead_of_failing_when_broker_is_down(settings: ApiSettings) -> None:
    link = MqttEdgeLink(settings, MetricsCache())
    sync = EdgeSync(_no_db, link, "s", "d")  # type: ignore[arg-type]
    assert await sync._send(sync.topics.rules, "{}") is False


def test_metrics_from_mqtt_use_the_topic_device() -> None:
    cache = MetricsCache()
    link = MqttEdgeLink(ApiSettings(), cache)
    payload = Metrics(
        device="spoofed", fps=12.5, verified_ratio=0.1, cpu_percent=40
    ).model_dump_json()
    link._on_metrics("aivee/demo/edge-01/metrics", payload.encode())
    link._on_metrics("aivee/demo/edge-02/metrics", b"not json")
    [sample] = cache.latest()
    assert (sample.site, sample.metrics.device, sample.metrics.fps) == ("demo", "edge-01", 12.5)
