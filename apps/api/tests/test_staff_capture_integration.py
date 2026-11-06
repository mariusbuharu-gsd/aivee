"""Guided staff capture end to end: live frames → candidates → confirm → profile published."""

import base64
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from aivee_api.db.repositories import DeviceRepository, StaffRepository
from aivee_api.deps import Services
from aivee_api.edge.publisher import RecordingPublisher
from aivee_api.main import create_app
from aivee_api.settings import ApiSettings
from aivee_api.staff import router as staff_router
from aivee_api.staff.enrol import Enroller
from aivee_contracts.topics import Topics

pytestmark = pytest.mark.integration

TOPICS = Topics(site="test", device="edge-01")


@pytest.fixture
def services(
    settings: ApiSettings,
    sessions: Any,
    publisher: RecordingPublisher,
    translator: Any,
    fake_enroller: Enroller,
    services_factory: Any,
) -> Services:
    svc: Services = services_factory(settings, sessions, publisher, translator, fake_enroller)
    return svc


@asynccontextmanager
async def _client(
    services: Services, sessions: Any, login: Any, email: str
) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(services)), base_url="http://test"
    ) as client:
        await login(client, email)
        yield client


@pytest.fixture
async def api(
    services: Services, sessions: Any, tenancy_factory: Any, login: Any
) -> AsyncIterator[httpx.AsyncClient]:
    await tenancy_factory(sessions)
    async with sessions() as s:
        await DeviceRepository(s).ensure_device("test", "edge-01")
        await s.commit()
    async with _client(services, sessions, login, "owner@t.ro") as client:
        r = await client.post(
            "/api/cameras", json={"id": "cam1", "name": "Sala", "source": "rtsp://x", "zones": []}
        )
        assert r.status_code == 201, r.text
        yield client


@pytest.fixture
def connector(services: Services, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[bytes]]:
    """Frames the "connector" posts, one per sample tick (the fake decoder reads byte 0:
    even = the employee is in the picture, odd = nobody)."""
    queue: list[bytes] = []

    async def tick(_: float) -> None:
        if queue:
            services.frames.put("cam1", queue.pop(0))

    monkeypatch.setattr(staff_router, "capture_sleep", tick)
    yield queue


async def test_capture_then_confirm_creates_a_published_profile(
    api: httpx.AsyncClient,
    services: Services,
    publisher: RecordingPublisher,
    sessions: Any,
    connector: list[bytes],
) -> None:
    services.frames.put("cam1", bytes([2]))
    connector.extend([bytes([3]), bytes([4])])  # 5 s at 1.5 s → 3 samples
    r = await api.post("/api/staff/capture", json={"camera_id": "cam1", "seconds": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["frames"] == 3
    assert [c["index"] for c in body["candidates"]] == [0, 1]
    thumb = body["candidates"][0]["thumbnail"]
    assert thumb.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(thumb.split(",", 1)[1]).endswith(b"crop-2")

    r = await api.post(
        f"/api/staff/capture/{body['token']}/confirm",
        json={"keep": [1], "name": "Ana", "description_ro": "șorț negru"},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["examples_added"] == 1 and out["published"] is True
    assert out["profile"]["name"] == "Ana" and out["profile"]["id"].startswith("staff-")

    msg = publisher.last(TOPICS.profiles)
    assert msg is not None
    [profile] = json.loads(msg.payload)["profiles"]
    assert profile["id"] == out["profile"]["id"]
    assert profile["centroid"][4] > 0.99  # only the kept crop (byte 4)

    again = await api.post(f"/api/staff/capture/{body['token']}/confirm", json={"keep": [0]})
    assert again.status_code == 404  # a token is used once

    async with sessions() as s:
        assert await StaffRepository(s).example_count(out["profile"]["id"]) == 1


async def test_capture_adds_to_an_existing_profile(
    api: httpx.AsyncClient, services: Services, connector: list[bytes]
) -> None:
    services.frames.put("cam1", bytes([6]))
    first = (await api.post("/api/staff/capture", json={"camera_id": "cam1", "seconds": 5})).json()
    created = (
        await api.post(
            f"/api/staff/capture/{first['token']}/confirm", json={"keep": [0], "name": "Ion"}
        )
    ).json()

    services.frames.put("cam1", bytes([8]))
    second = (await api.post("/api/staff/capture", json={"camera_id": "cam1", "seconds": 5})).json()
    r = await api.post(
        f"/api/staff/capture/{second['token']}/confirm",
        json={"keep": [0], "profile_id": created["profile"]["id"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["profile"] == {**created["profile"], "examples": 2}


async def test_capture_errors_are_romanian(
    api: httpx.AsyncClient, services: Services, connector: list[bytes]
) -> None:
    r = await api.post("/api/staff/capture", json={"camera_id": "cam1"})
    assert r.status_code == 404 and "nu trimite imagini" in r.json()["detail"]["message_ro"]

    services.frames.put("cam1", bytes([3]))  # nobody in the picture
    r = await api.post("/api/staff/capture", json={"camera_id": "cam1", "seconds": 5})
    assert r.status_code == 422 and "nimeni" in r.json()["detail"]["message_ro"]

    assert (
        await api.post("/api/staff/capture", json={"camera_id": "cam1", "seconds": 60})
    ).status_code == 422
    r = await api.post("/api/staff/capture", json={"camera_id": "nope", "seconds": 5})
    assert r.status_code == 404

    services.frames.put("cam1", bytes([2]))
    token = (await api.post("/api/staff/capture", json={"camera_id": "cam1", "seconds": 5})).json()[
        "token"
    ]
    r = await api.post(f"/api/staff/capture/{token}/confirm", json={"keep": [0]})
    assert r.status_code == 422 and "numele" in r.json()["detail"]["message_ro"]
    r = await api.post(f"/api/staff/capture/{token}/confirm", json={"keep": [5], "name": "X"})
    assert r.status_code == 422
    r = await api.post(
        f"/api/staff/capture/{token}/confirm", json={"keep": [0], "profile_id": "missing"}
    )
    assert r.status_code == 404


async def test_capture_is_owned_by_its_user_and_needs_staff_enrol(
    api: httpx.AsyncClient,
    services: Services,
    sessions: Any,
    login: Any,
    connector: list[bytes],
) -> None:
    services.frames.put("cam1", bytes([2]))
    token = (await api.post("/api/staff/capture", json={"camera_id": "cam1", "seconds": 5})).json()[
        "token"
    ]
    async with _client(services, sessions, login, "manager@t.ro") as manager:
        r = await manager.post(
            f"/api/staff/capture/{token}/confirm", json={"keep": [0], "name": "X"}
        )
        assert r.status_code == 404
    async with _client(services, sessions, login, "staff@t.ro") as staff:
        r = await staff.post("/api/staff/capture", json={"camera_id": "cam1", "seconds": 5})
        assert r.status_code == 403
    async with _client(services, sessions, login, "other@t.ro") as other:
        r = await other.post("/api/staff/capture", json={"camera_id": "cam1", "seconds": 5})
        assert r.status_code == 404


async def test_capture_without_models_is_503(
    api: httpx.AsyncClient, services: Services, connector: list[bytes]
) -> None:
    services.enroller = None
    services.frames.put("cam1", bytes([2]))
    r = await api.post("/api/staff/capture", json={"camera_id": "cam1", "seconds": 5})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "unavailable"
