"""The camera password reaches the edge (retained DeviceConfig) and nowhere else: not in the
camera list, a single camera, the create/update answers or the audit log."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from aivee_api.db.repositories import DeviceRepository
from aivee_api.deps import Services
from aivee_api.edge.publisher import RecordingPublisher
from aivee_api.main import create_app
from aivee_contracts.topics import Topics

pytestmark = pytest.mark.integration

CONFIG = Topics(site="test", device="edge-01").config
REAL = "rtsp://admin:s3cr3tPw@192.168.1.21:554/stream2"
SHOWN = "rtsp://admin:***@192.168.1.21:554/stream2"


@pytest.fixture
async def api(
    services: Services, sessions: Any, tenancy_factory: Any, login: Any
) -> AsyncIterator[httpx.AsyncClient]:
    await tenancy_factory(sessions)
    async with sessions() as s:
        await DeviceRepository(s).ensure_device("test", "edge-01")
        await s.commit()
    transport = httpx.ASGITransport(app=create_app(services))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "owner@t.ro")
        yield client


def _edge_source(publisher: RecordingPublisher) -> str:
    msg = publisher.last(CONFIG)
    assert msg is not None
    [camera] = json.loads(msg.payload)["cameras"]
    source: str = camera["source"]
    return source


async def test_password_goes_to_the_edge_and_is_masked_everywhere_else(
    api: httpx.AsyncClient, publisher: RecordingPublisher
) -> None:
    r = await api.post("/api/cameras", json={"id": "cam1", "name": "Sala", "source": REAL})
    assert r.status_code == 201, r.text
    assert r.json()["source"] == SHOWN
    assert _edge_source(publisher) == REAL
    assert (await api.get("/api/cameras")).json()[0]["source"] == SHOWN
    assert (await api.get("/api/cameras/cam1")).json()["source"] == SHOWN

    r = await api.patch("/api/cameras/cam1", json={"name": "Sala mare"})
    assert r.json()["source"] == SHOWN
    audit = (await api.get("/api/audit")).text
    assert "s3cr3tPw" not in audit and SHOWN in audit


async def test_an_edit_that_keeps_the_mask_keeps_the_password(
    api: httpx.AsyncClient, publisher: RecordingPublisher
) -> None:
    await api.post("/api/cameras", json={"id": "cam1", "name": "Sala", "source": REAL})
    # The dashboard's edit form: new IP, the password left empty → the masked value comes back.
    r = await api.patch(
        "/api/cameras/cam1", json={"source": "rtsp://admin:***@192.168.1.22:554/stream2"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "rtsp://admin:***@192.168.1.22:554/stream2"
    assert _edge_source(publisher) == "rtsp://admin:s3cr3tPw@192.168.1.22:554/stream2"

    r = await api.put("/api/cameras/cam1", json={"source": "rtsp://admin:nou@192.168.1.22/stream1"})
    assert r.status_code == 200
    assert _edge_source(publisher) == "rtsp://admin:nou@192.168.1.22/stream1"


async def test_a_mask_without_a_stored_password_is_refused(api: httpx.AsyncClient) -> None:
    r = await api.post("/api/cameras", json={"id": "cam1", "name": "Sala", "source": SHOWN})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid"
    await api.post(
        "/api/cameras", json={"id": "cam2", "name": "Bar", "source": "rtsp://192.168.1.23/s"}
    )
    r = await api.patch("/api/cameras/cam2", json={"source": "rtsp://admin:***@192.168.1.23/s"})
    assert r.status_code == 422
