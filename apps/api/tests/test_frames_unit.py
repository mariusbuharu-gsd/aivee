"""Cloud frames over HTTPS without a database: ingest auth and limits, relay, MJPEG parts."""

import asyncio
import base64
from typing import Any

import httpx
import pytest
from aivee_api.edge.publisher import PublisherUnavailable, RecordingPublisher
from aivee_api.frames.router import credentials_ok, get_camera_topics
from aivee_api.frames.store import BOUNDARY, LiveFrames, mjpeg_part, mjpeg_stream
from aivee_api.main import create_app
from aivee_api.settings import ApiSettings
from aivee_contracts.topics import Topics

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100 + b"\xff\xd9"
USER, PASSWORD = "pub", "s3cret-pass"


def basic(user: str = USER, password: str = PASSWORD) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def frame_settings(settings: ApiSettings) -> ApiSettings:
    return settings.model_copy(
        update={"stream_publish_user": USER, "stream_publish_password": PASSWORD}
    )


@pytest.fixture
def frames(publisher: RecordingPublisher) -> LiveFrames:
    return LiveFrames(publisher)


@pytest.fixture
def client(
    frame_settings: ApiSettings,
    publisher: RecordingPublisher,
    frames: LiveFrames,
    translator: Any,
    services_factory: Any,
) -> httpx.AsyncClient:
    def no_db() -> Any:
        raise AssertionError("frame ingest must not touch the database here")

    svc = services_factory(frame_settings, no_db, publisher, translator)
    svc.frames = frames
    app = create_app(svc)

    async def find(camera_id: str) -> Topics | None:
        return Topics(site="test", device="vision-01") if camera_id == "cam1" else None

    app.dependency_overrides[get_camera_topics] = lambda: find
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.parametrize(
    "headers",
    [
        {},
        basic(password="wrong"),
        basic(user="other"),
        {"Authorization": "Bearer abc"},
        {"Authorization": "Basic not-base64!"},
        {"Authorization": "Basic " + base64.b64encode(b"no-colon").decode()},
    ],
)
async def test_ingest_rejects_missing_or_wrong_credentials(
    client: httpx.AsyncClient, publisher: RecordingPublisher, headers: dict[str, str]
) -> None:
    r = await client.post("/api/ingest/frames/cam1", content=JPEG, headers=headers)
    assert r.status_code == 401
    assert publisher.messages == []


def test_empty_publish_credentials_reject_everyone(settings: ApiSettings) -> None:
    assert not credentials_ok(basic()["Authorization"], settings)
    assert not credentials_ok(basic("", "")["Authorization"], settings)


async def test_ingest_keeps_the_frame_and_relays_it_to_the_cameras_worker(
    client: httpx.AsyncClient, publisher: RecordingPublisher, frames: LiveFrames
) -> None:
    r = await client.post("/api/ingest/frames/cam1", content=JPEG, headers=basic())
    assert r.status_code == 204
    [msg] = publisher.messages
    assert msg.topic == Topics(site="test", device="vision-01").frames("cam1")
    assert msg.topic == "aivee/test/vision-01/frames/cam1"
    assert (msg.payload, msg.qos, msg.retain) == (JPEG, 0, False)
    latest = frames.latest("cam1")
    assert latest is not None and latest.jpeg == JPEG


async def test_ingest_limits_size_and_type(
    client: httpx.AsyncClient, frame_settings: ApiSettings, publisher: RecordingPublisher
) -> None:
    big = JPEG + b"x" * frame_settings.frame_max_bytes
    r = await client.post("/api/ingest/frames/cam1", content=big, headers=basic())
    assert r.status_code == 413

    async def chunks() -> Any:  # no Content-Length: the limit applies while reading
        yield JPEG
        yield b"x" * frame_settings.frame_max_bytes

    r = await client.post("/api/ingest/frames/cam1", content=chunks(), headers=basic())
    assert r.status_code == 413
    r = await client.post("/api/ingest/frames/cam1", content=b"\x89PNG\r\n\x1a\n", headers=basic())
    assert r.status_code == 415
    r = await client.post("/api/ingest/frames/cam1", content=b"", headers=basic())
    assert r.status_code == 415
    assert publisher.messages == []


async def test_ingest_for_an_unknown_camera_is_404(
    client: httpx.AsyncClient, publisher: RecordingPublisher, frames: LiveFrames
) -> None:
    r = await client.post("/api/ingest/frames/nope", content=JPEG, headers=basic())
    assert r.status_code == 404
    assert publisher.messages == [] and frames.latest("nope") is None
    r = await client.post("/api/ingest/frames/bad id!", content=JPEG, headers=basic())
    assert r.status_code == 422


async def test_live_mjpeg_needs_a_session(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/cameras/cam1/live.mjpg")
    assert r.status_code == 401


async def test_relay_drops_frames_while_the_broker_is_down() -> None:
    class Down:
        async def publish(self, topic: str, payload: bytes, *, qos: int, retain: bool) -> None:
            raise PublisherUnavailable("down")

    assert await LiveFrames(Down()).relay("t", JPEG) is False
    assert await LiveFrames(None).relay("t", JPEG) is False


def test_old_frames_are_not_live() -> None:
    now = [100.0]
    frames = LiveFrames(max_age_s=10, clock=lambda: now[0])
    frames.put("cam1", JPEG)
    assert frames.latest("cam1") is not None
    now[0] = 111.0
    assert frames.latest("cam1") is None


def test_mjpeg_part_has_boundary_type_and_length() -> None:
    part = mjpeg_part(JPEG)
    assert part.startswith(f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n".encode())
    assert f"Content-Length: {len(JPEG)}\r\n\r\n".encode() in part
    assert part.endswith(JPEG + b"\r\n")


async def test_mjpeg_stream_yields_each_new_frame_once_and_stops_on_disconnect() -> None:
    frames = LiveFrames()
    frames.put("cam1", JPEG)
    gone = asyncio.Event()

    async def disconnected() -> bool:
        return gone.is_set()

    stream = mjpeg_stream(frames, "cam1", fps=100, disconnected=disconnected, poll_s=0.05)
    first = await anext(stream)
    assert first == mjpeg_part(JPEG)

    second_jpeg = JPEG.replace(b"x", b"y")
    pending = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0.03)
    assert not pending.done()  # waits for a newer frame instead of repeating the old one
    frames.put("cam1", second_jpeg)
    assert await asyncio.wait_for(pending, 1) == mjpeg_part(second_jpeg)

    gone.set()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), 1)


async def test_mjpeg_stream_ends_when_frames_stop() -> None:
    frames = LiveFrames()
    frames.put("cam1", JPEG)

    async def connected() -> bool:
        return False

    parts = [
        p
        async for p in mjpeg_stream(
            frames, "cam1", fps=100, disconnected=connected, idle_s=0.1, poll_s=0.05
        )
    ]
    assert parts == [mjpeg_part(JPEG)]
