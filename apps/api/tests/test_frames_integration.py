"""Cloud frames against a real Postgres: the camera must exist, live.mjpg is scoped by location."""

import base64
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from aivee_api.db.repositories import DeviceRepository
from aivee_api.deps import Services
from aivee_api.edge.publisher import RecordingPublisher
from aivee_api.frames.store import BOUNDARY, LiveFrames
from aivee_api.main import create_app
from aivee_api.settings import ApiSettings

pytestmark = pytest.mark.integration

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 64 + b"\xff\xd9"
AUTH = {"Authorization": "Basic " + base64.b64encode(b"pub:s3cret").decode()}


@pytest.fixture
async def app_parts(
    settings: ApiSettings,
    sessions: Any,
    publisher: RecordingPublisher,
    translator: Any,
    services_factory: Any,
    tenancy_factory: Any,
) -> AsyncIterator[tuple[Any, Services]]:
    s = settings.model_copy(
        update={
            "stream_publish_user": "pub",
            "stream_publish_password": "s3cret",
            "live_idle_s": 0.3,
        }
    )
    svc: Services = services_factory(s, sessions, publisher, translator)
    svc.frames = LiveFrames(publisher)
    await tenancy_factory(sessions)
    async with sessions() as db:
        await DeviceRepository(db).ensure_device("test", "edge-01")
        await db.commit()
    yield create_app(svc), svc


async def _client(app: Any, login: Any, email: str) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    await login(client, email)
    return client


async def test_frames_need_an_existing_camera_and_stream_to_its_location(
    app_parts: tuple[Any, Services], publisher: RecordingPublisher, login: Any
) -> None:
    app, _ = app_parts
    owner = await _client(app, login, "owner@t.ro")
    r = await owner.post("/api/ingest/frames/cam1", content=JPEG, headers=AUTH)
    assert r.status_code == 404

    r = await owner.post("/api/cameras", json={"id": "cam1", "name": "Sala", "source": "x"})
    assert r.status_code == 201, r.text
    r = await owner.get("/api/cameras/cam1/live.mjpg")
    assert r.status_code == 404  # no frame yet: the dashboard falls back

    r = await owner.post("/api/ingest/frames/cam1", content=JPEG, headers=AUTH)
    assert r.status_code == 204
    assert publisher.last("aivee/test/edge-01/frames/cam1") is not None

    started = time.monotonic()
    r = await owner.get("/api/cameras/cam1/live.mjpg")  # ends after live_idle_s without frames
    assert r.status_code == 200
    assert time.monotonic() - started < 5
    assert r.headers["content-type"] == f"multipart/x-mixed-replace; boundary={BOUNDARY}"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-accel-buffering"] == "no"
    assert r.content.startswith(f"--{BOUNDARY}\r\n".encode()) and JPEG in r.content

    other = await _client(app, login, "other@t.ro")  # manager of another location
    assert (await other.get("/api/cameras/cam1/live.mjpg")).status_code == 404
    await owner.aclose()
    await other.aclose()
