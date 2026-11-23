"""Cloud frames against a real Postgres: the camera must exist, live.mjpg is scoped by location."""

import base64
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from aivee_api.audit.models import AuditRow
from aivee_api.db.models import Camera
from aivee_api.db.repositories import CameraRepository, DeviceRepository
from aivee_api.deps import Services
from aivee_api.edge.publisher import RecordingPublisher
from aivee_api.frames.store import BOUNDARY, LiveFrames
from aivee_api.main import create_app
from aivee_api.settings import ApiSettings
from aivee_contracts.geometry import CameraConfig
from sqlalchemy import select

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


async def test_a_dashboard_session_can_push_frames_to_a_cloud_camera(
    app_parts: tuple[Any, Services], publisher: RecordingPublisher, login: Any
) -> None:
    """The phone page posts with the session cookie and no Basic header."""
    app, svc = app_parts
    owner = await _client(app, login, "owner@t.ro")
    cloud = {"id": "phone1", "name": "Telefon", "source": "mqtt-frames://phone1"}
    assert (await owner.post("/api/cameras", json=cloud)).status_code == 201
    r = await owner.post("/api/cameras", json={"id": "rtsp1", "name": "Sala", "source": "rtsp://x"})
    assert r.status_code == 201

    r = await owner.post("/api/ingest/frames/phone1", content=JPEG)
    assert r.status_code == 204, r.text
    assert publisher.last("aivee/test/edge-01/frames/phone1") is not None
    assert svc.frames.latest("phone1") is not None

    manager = await _client(app, login, "manager@t.ro")
    assert (await manager.post("/api/ingest/frames/phone1", content=JPEG)).status_code == 204

    r = await owner.post("/api/ingest/frames/rtsp1", content=JPEG)
    assert r.status_code == 409  # only cloud cameras take frames from a browser
    assert svc.frames.latest("rtsp1") is None

    r = await owner.post("/api/ingest/frames/phone1", content=b"\x89PNG\r\n\x1a\n")
    assert r.status_code == 415
    r = await owner.post(
        "/api/ingest/frames/phone1", content=JPEG + b"x" * svc.settings.frame_max_bytes
    )
    assert r.status_code == 413

    staff = await _client(app, login, "staff@t.ro")
    r = await staff.post("/api/ingest/frames/phone1", content=JPEG)
    assert r.status_code == 403

    other = await _client(app, login, "other@t.ro")  # manager of another location
    assert (await other.post("/api/ingest/frames/phone1", content=JPEG)).status_code == 404

    anon = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    assert (await anon.post("/api/ingest/frames/phone1", content=JPEG)).status_code == 401
    assert (
        await anon.post("/api/ingest/frames/phone1", content=JPEG, headers=AUTH)
    ).status_code == 204
    for c in (owner, manager, staff, other, anon):
        await c.aclose()


# S6: the shared publish credential reaches only claimed locations; a camera with its own push
# key takes frames only with that key.


async def test_the_shared_credential_cannot_push_to_a_camera_of_an_unclaimed_location(
    app_parts: tuple[Any, Services], publisher: RecordingPublisher
) -> None:
    app, svc = app_parts
    async with svc.sessions() as db:
        # Ingest auto-creates a site for an unknown device: it has no organization.
        await DeviceRepository(db).ensure_device("stray-site", "edge-stray")
        await CameraRepository(db).upsert(
            CameraConfig(id="cam-stray", name="X", source="mqtt-frames://cam-stray"), "edge-stray"
        )
        await db.commit()
    anon = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    r = await anon.post("/api/ingest/frames/cam-stray", content=JPEG, headers=AUTH)
    assert r.status_code == 404
    assert publisher.messages == [] and svc.frames.latest("cam-stray") is None
    await anon.aclose()


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def test_a_camera_push_key_replaces_the_shared_credential_for_that_camera(
    app_parts: tuple[Any, Services], login: Any
) -> None:
    app, svc = app_parts
    owner = await _client(app, login, "owner@t.ro")
    for cam in ("cam1", "cam2"):
        body = {"id": cam, "name": cam, "source": f"mqtt-frames://{cam}"}
        assert (await owner.post("/api/cameras", json=body)).status_code == 201

    r = await owner.post("/api/cameras/cam1/push-key")
    assert r.status_code == 201, r.text
    key = r.json()["key"]
    assert r.json()["camera_id"] == "cam1" and len(key) >= 32

    anon = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def push(camera_id: str, headers: dict[str, str]) -> int:
        r = await anon.post(f"/api/ingest/frames/{camera_id}", content=JPEG, headers=headers)
        return r.status_code

    assert await push("cam1", bearer(key)) == 204
    assert svc.frames.latest("cam1") is not None
    # The key works for its own camera only, and the shared credential no longer does.
    assert await push("cam2", bearer(key)) == 401
    assert await push("cam1", AUTH) == 401
    assert await push("cam1", bearer("x" * 43)) == 401
    assert await push("nope", bearer(key)) == 401
    # cam2 has no key yet: the shared credential still works there (connectors migrate).
    assert await push("cam2", AUTH) == 204

    # A new key revokes the old one.
    new = (await owner.post("/api/cameras/cam1/push-key")).json()["key"]
    assert await push("cam1", bearer(key)) == 401
    assert await push("cam1", bearer(new)) == 204

    staff = await _client(app, login, "staff@t.ro")
    assert (await staff.post("/api/cameras/cam1/push-key")).status_code == 403
    other = await _client(app, login, "other@t.ro")
    assert (await other.post("/api/cameras/cam1/push-key")).status_code == 404

    async with svc.sessions() as db:
        stored = await db.scalar(select(Camera.push_key_hash).where(Camera.id == "cam1"))
        entries = (
            await db.scalars(select(AuditRow).where(AuditRow.kind == "camera.push_key_created"))
        ).all()
    assert stored is not None and len(stored) == 64 and new not in stored
    assert len(entries) == 2 and all(new not in str(e.after) for e in entries)
    for c in (owner, anon, staff, other):
        await c.aclose()
