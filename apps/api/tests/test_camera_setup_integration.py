"""Camera setup from the dashboard: `POST /api/devices/{id}/discover` and `POST /api/cameras/test`
against a real Postgres, with a fake edge answering the MQTT requests."""

import base64
import contextlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from aivee_api.db.repositories import CameraRepository, DeviceRepository
from aivee_api.deps import Services
from aivee_api.edge.requests import EdgeTimeout, EdgeUnreachable
from aivee_api.main import create_app
from aivee_contracts.commands import DiscoveredCamera, EdgeReply, RequestKind
from aivee_contracts.events import DeviceStatus
from aivee_contracts.geometry import CameraConfig

pytestmark = pytest.mark.integration

AT = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
REAL = "rtsp://admin:s3cr3tPw@192.168.1.21:554/stream2"
JPEG = b"\xff\xd8\xff\xe0blurred"


@dataclass
class FakeEdge:
    """Answers `ask` with `answer(device, kind, source)`; an exception is raised instead."""

    answer: Callable[[str, str, str | None], EdgeReply | Exception] = lambda d, k, s: _ok(d, k)
    calls: list[tuple[str, str, str | None, float]] = field(default_factory=list)

    async def ask(
        self, device: str, kind: RequestKind, *, source: str | None = None, timeout_s: float
    ) -> EdgeReply:
        self.calls.append((device, kind, source, timeout_s))
        reply = self.answer(device, kind, source)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _ok(device: str, kind: str, **fields: Any) -> EdgeReply:
    base: dict[str, Any] = {"request_id": "r", "kind": kind, "device": device, "ok": True, "at": AT}
    if kind == "test_camera":
        base |= {
            "jpeg_b64": base64.b64encode(JPEG).decode(),
            "width": 640,
            "height": 360,
            "frame_at": AT,
        }
    return EdgeReply.model_validate(base | fields)


def _error(code: str) -> Callable[[str, str, str | None], EdgeReply]:
    return lambda d, k, s: EdgeReply(
        request_id="r",
        kind=k,  # type: ignore[arg-type]
        device=d,
        ok=False,
        error=code,  # type: ignore[arg-type]
        at=AT,
    )


@pytest.fixture
def edge() -> FakeEdge:
    return FakeEdge()


@pytest.fixture
def services(services: Services, edge: FakeEdge) -> Services:
    services.edge_requests = edge
    return services


async def _online(sessions: Any, site: str, device: str, state: str = "online") -> None:
    async with sessions() as s:
        await DeviceRepository(s).apply_status(site, DeviceStatus(device=device, state=state))  # type: ignore[arg-type]
        await s.commit()


@pytest.fixture
async def world(sessions: Any, tenancy_factory: Any) -> None:
    """`test`: edge-01 online with cam1 (Tapo, password stored), edge-02 offline, vision-01
    online serving only a cloud camera. `far` (another org): edge-far online."""
    await tenancy_factory(sessions)
    await _online(sessions, "test", "edge-01")
    await _online(sessions, "test", "edge-02", "offline")
    await _online(sessions, "test", "vision-01")
    await _online(sessions, "far", "edge-far")
    async with sessions() as s:
        cams = CameraRepository(s)
        await cams.upsert(CameraConfig(id="cam1", name="Sala", source=REAL), "edge-01")
        await cams.upsert(
            CameraConfig(id="phone", name="Telefon", source="mqtt-frames://phone"), "vision-01"
        )
        await cams.upsert(
            CameraConfig(id="camfar", name="Far", source="rtsp://10.9.9.9/stream2"), "edge-far"
        )
        await s.commit()


@contextlib.asynccontextmanager
async def _client(services: Services, login: Any, email: str) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(services))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, email)
        yield client


@pytest.fixture
async def api(services: Services, world: None, login: Any) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(services, login, "owner@t.ro") as client:
        yield client


# -- discovery --------------------------------------------------------------------------------


async def test_discover_lists_the_cameras_and_marks_those_already_added(
    api: httpx.AsyncClient, edge: FakeEdge
) -> None:
    found = [
        DiscoveredCamera(
            ip="192.168.1.21",
            brand="tapo",
            model="C210",
            name="TP-IPC",
            onvif=True,
            rtsp_paths=["/stream2", "/stream1"],
        ),
        DiscoveredCamera(
            ip="192.168.1.64", brand="hikvision", rtsp_paths=["/Streaming/Channels/102"]
        ),
    ]
    edge.answer = lambda d, k, s: _ok(d, k, cameras=found)
    r = await api.post("/api/devices/edge-01/discover")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "cameras": [
            {
                "ip": "192.168.1.21",
                "port": 554,
                "brand": "tapo",
                "model": "C210",
                "name": "TP-IPC",
                "onvif": True,
                "rtsp_paths": ["/stream2", "/stream1"],
                "already_added": True,
            },
            {
                "ip": "192.168.1.64",
                "port": 554,
                "brand": "hikvision",
                "model": None,
                "name": None,
                "onvif": False,
                "rtsp_paths": ["/Streaming/Channels/102"],
                "already_added": False,
            },
        ]
    }
    assert edge.calls == [("edge-01", "discover_cameras", None, 15.0)]


async def test_discover_errors(api: httpx.AsyncClient, edge: FakeEdge) -> None:
    r = await api.post("/api/devices/edge-02/discover")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "device_offline" and r.json()["detail"]["message_ro"]
    for device in ("edge-far", "nope"):
        assert (await api.post(f"/api/devices/{device}/discover")).status_code == 404
    edge.answer = lambda d, k, s: EdgeTimeout()
    r = await api.post("/api/devices/edge-01/discover")
    assert r.status_code == 504 and r.json()["detail"]["code"] == "device_timeout"
    edge.answer = _error("failed")
    r = await api.post("/api/devices/edge-01/discover")
    assert r.status_code == 502 and r.json()["detail"]["code"] == "device_error"
    edge.answer = lambda d, k, s: EdgeUnreachable()
    assert (await api.post("/api/devices/edge-01/discover")).status_code == 503
    assert [c[0] for c in edge.calls] == ["edge-01"] * 3


async def test_discover_needs_devices_manage(services: Services, world: None, login: Any) -> None:
    async with _client(services, login, "staff@t.ro") as staff:
        assert (await staff.post("/api/devices/edge-01/discover")).status_code == 403


async def test_discover_takes_the_dashboard_location(
    api: httpx.AsyncClient, edge: FakeEdge
) -> None:
    r = await api.post("/api/devices/edge-01/discover", params={"location_id": "test"})
    assert r.status_code == 200
    # The device is not at the location the dashboard is on: as if it did not exist.
    r = await api.post("/api/devices/edge-01/discover", params={"location_id": "other"})
    assert r.status_code == 404
    assert len(edge.calls) == 1


async def test_without_mqtt_camera_setup_is_unavailable(
    services: Services, world: None, login: Any
) -> None:
    services.edge_requests = None
    async with _client(services, login, "owner@t.ro") as client:
        r = await client.post("/api/devices/edge-01/discover")
        assert r.status_code == 503
        r = await client.post("/api/cameras/test", json={"source": "rtsp://a/b"})
        assert r.status_code == 503


# -- camera test ------------------------------------------------------------------------------


async def test_a_new_source_is_tested_on_the_only_box_of_the_location(
    api: httpx.AsyncClient, edge: FakeEdge
) -> None:
    source = "rtsp://admin:nou@192.168.1.22:554/stream2"
    r = await api.post("/api/cameras/test", params={"location_id": "test"}, json={"source": source})
    assert r.status_code == 200, r.text
    assert r.content == JPEG and r.headers["content-type"] == "image/jpeg"
    assert r.headers["X-Frame-At"] == AT.isoformat()
    assert r.headers["X-Frame-Size"] == "640x360"
    assert r.headers["Cache-Control"] == "no-store"
    # vision-01 (cloud cameras only) and the offline edge-02 are not candidates.
    assert edge.calls == [("edge-01", "test_camera", source, 10.0)]


async def test_a_saved_camera_is_tested_with_its_stored_password(
    api: httpx.AsyncClient, edge: FakeEdge
) -> None:
    r = await api.post("/api/cameras/test", json={"camera_id": "cam1"})
    assert r.status_code == 200
    assert edge.calls[-1][:3] == ("edge-01", "test_camera", REAL)
    # The edit form: a new IP, the password left masked.
    r = await api.post(
        "/api/cameras/test",
        json={"camera_id": "cam1", "source": "rtsp://admin:***@192.168.1.23:554/stream2"},
    )
    assert r.status_code == 200
    assert edge.calls[-1][2] == "rtsp://admin:s3cr3tPw@192.168.1.23:554/stream2"


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"source": "rtsp://admin:***@192.168.1.22/stream2"}, 422, "invalid"),
        ({"source": "0"}, 422, "invalid"),
        ({"source": "mqtt-frames://phone"}, 422, "invalid"),
        ({}, 422, "invalid"),
        ({"camera_id": "camfar"}, 404, "not_found"),
        ({"camera_id": "nope"}, 404, "not_found"),
        ({"source": "rtsp://a/b", "device": "edge-far"}, 404, "not_found"),
        ({"source": "rtsp://a/b", "device": "edge-02"}, 409, "device_offline"),
    ],
)
async def test_camera_test_input_errors(
    api: httpx.AsyncClient, edge: FakeEdge, body: dict[str, Any], status: int, code: str
) -> None:
    r = await api.post("/api/cameras/test", json=body)
    assert r.status_code == status, r.text
    assert r.json()["detail"]["code"] == code
    assert edge.calls == []


@pytest.mark.parametrize(
    ("error", "source", "words"),
    [
        ("camera_auth", "rtsp://admin:x@192.168.1.22/stream2", ["parolă greșită", "Cont cameră"]),
        ("camera_auth", "rtsp://admin:x@192.168.1.64/Streaming/Channels/102", ["parolă greșită"]),
        ("camera_unreachable", "rtsp://a:x@192.168.1.99/stream2", ["nu răspunde", "aceeași rețea"]),
        ("camera_no_stream", "rtsp://a:x@192.168.1.22/streamX", ["nu trimite imagine"]),
    ],
)
async def test_camera_failures_are_explained_in_romanian(
    api: httpx.AsyncClient, edge: FakeEdge, error: str, source: str, words: list[str]
) -> None:
    edge.answer = _error(error)
    r = await api.post("/api/cameras/test", json={"source": source})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == error
    assert all(w in detail["message_ro"] for w in words), detail["message_ro"]
    if "Streaming" in source:
        assert "Tapo" not in detail["message_ro"]
    assert ":x@" not in r.text


async def test_tapo_auth_hint_mentions_third_party_compatibility(
    api: httpx.AsyncClient, edge: FakeEdge
) -> None:
    edge.answer = _error("camera_auth")
    r = await api.post("/api/cameras/test", json={"source": "rtsp://a:x@192.168.1.22/stream1"})
    assert "Third-Party Compatibility" in r.json()["detail"]["message_ro"]


async def test_several_boxes_need_a_choice_and_none_is_offline(
    api: httpx.AsyncClient, edge: FakeEdge, sessions: Any
) -> None:
    await _online(sessions, "test", "edge-02")
    r = await api.post("/api/cameras/test", json={"source": "rtsp://a:x@192.168.1.22/stream2"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "device_required"
    r = await api.post(
        "/api/cameras/test", json={"source": "rtsp://a:x@192.168.1.22/stream2", "device": "edge-02"}
    )
    assert r.status_code == 200 and edge.calls[-1][0] == "edge-02"
    # A saved camera goes to its own device.
    assert (await api.post("/api/cameras/test", json={"camera_id": "cam1"})).status_code == 200
    assert edge.calls[-1][0] == "edge-01"

    await _online(sessions, "test", "edge-01", "offline")
    await _online(sessions, "test", "edge-02", "offline")
    r = await api.post("/api/cameras/test", json={"source": "rtsp://a:x@192.168.1.22/stream2"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "device_offline"
    r = await api.post("/api/cameras/test", json={"camera_id": "cam1"})
    assert r.status_code == 409


async def test_camera_test_timeout_and_broken_box(api: httpx.AsyncClient, edge: FakeEdge) -> None:
    edge.answer = lambda d, k, s: EdgeTimeout()
    r = await api.post("/api/cameras/test", json={"source": "rtsp://a:x@192.168.1.22/stream2"})
    assert r.status_code == 504 and r.json()["detail"]["code"] == "device_timeout"
    edge.answer = _error("failed")
    r = await api.post("/api/cameras/test", json={"source": "rtsp://a:x@192.168.1.22/stream2"})
    assert r.status_code == 502 and r.json()["detail"]["code"] == "device_error"


async def test_camera_test_needs_devices_manage_at_the_location(
    services: Services, world: None, login: Any
) -> None:
    async with _client(services, login, "staff@t.ro") as staff:
        r = await staff.post("/api/cameras/test", json={"source": "rtsp://a/b"})
        assert r.status_code == 403
    async with _client(services, login, "other@t.ro") as other:
        r = await other.post(
            "/api/cameras/test", params={"location_id": "test"}, json={"source": "rtsp://a/b"}
        )
        assert r.status_code == 404
