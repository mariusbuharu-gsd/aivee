"""Camera setup from the dashboard, done by the venue's edge device over MQTT request/reply:

- `POST /api/devices/{device_id}/discover`: the device looks for IP cameras on its network.
- `POST /api/cameras/test`: the device opens a camera once and sends back a face-blurred still.

Both need `devices.manage` at the device's (or the given) location and an online device; the
device must answer within 15 s (discovery) or 10 s (test). Errors carry a `code` and a short
Romanian `message_ro` the dashboard shows as is. Camera passwords travel to the device only.
"""

import base64
from typing import Annotated

from aivee_contracts.commands import EdgeReply, RequestKind
from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from aivee_api.auth.deps import Access, CurrentUser, require
from aivee_api.auth.permissions import DEVICES_MANAGE
from aivee_api.auth.scope import authorize_at, camera_location, device_location
from aivee_api.cameras.masking import (
    MaskedWithoutPassword,
    is_masked,
    restore_masked,
    url_host,
)
from aivee_api.cameras.schemas import ID_PATTERN
from aivee_api.db.models import Device
from aivee_api.db.repositories import CameraRepository, DeviceRepository
from aivee_api.deps import Services, ServicesDep, SessionDep
from aivee_api.edge.requests import EdgeAsk, EdgeTimeout, EdgeUnreachable
from aivee_api.errors import DomainError, Invalid, NotFound, Unavailable
from aivee_api.frames.router import CLOUD_SOURCE
from aivee_api.videos.kind import is_upload_device

router = APIRouter(prefix="/api", tags=["camera setup"])

DISCOVER_TIMEOUT_S = 15.0
TEST_TIMEOUT_S = 10.0
LIVE_SCHEMES = ("rtsp://", "rtsps://", "http://", "https://")

DEVICE_OFFLINE_RO = (
    "Cutia AiVee nu este conectată. Verifică să fie pornită și legată la internet, "
    "apoi încearcă din nou."
)
DEVICE_TIMEOUT_RO = "Cutia AiVee nu a răspuns la timp. Încearcă din nou peste câteva secunde."
DEVICE_REQUIRED_RO = "Locația are mai multe cutii AiVee conectate. Alege cutia din rețeaua camerei."
DEVICE_ERROR_RO = (
    "Cutia AiVee nu a putut face verificarea. Încearcă din nou; dacă se repetă, repornește cutia."
)
NO_BROKER_RO = "Serverul nu este conectat acum la cutiile AiVee. Încearcă din nou peste un minut."
NO_EDGE_LINK_RO = "Căutarea și testarea camerelor nu sunt disponibile pe acest server."
CAMERA_AUTH_RO = "Utilizator sau parolă greșită pentru cameră."
TAPO_AUTH_HINT_RO = (
    " La Tapo: folosește „Cont cameră” din aplicație (camera → Setări → Setări avansate), "
    "nu contul TP-Link, și pornește Tapo Lab → „Third-Party Compatibility”."
)
CAMERA_UNREACHABLE_RO = (
    "Camera nu răspunde. Verifică IP-ul și că e în aceeași rețea cu cutia AiVee."
)
CAMERA_NO_STREAM_RO = (
    "Camera răspunde, dar nu trimite imagine la această adresă. Verifică calea fluxului "
    "(la Tapo /stream2) și închide alte aplicații care o urmăresc."
)
BAD_SOURCE_RO = (
    "Adresa camerei trebuie să fie RTSP sau HTTP, de exemplu rtsp://192.168.1.21:554/stream2."
)
NO_SOURCE_RO = "Scrie adresa camerei sau alege o cameră salvată."
MASKED_RO = "Scrie parola camerei: „***” ține doar locul parolei unei camere salvate."
TAPO_PATHS = ("/stream1", "/stream2")


class SetupError(DomainError):
    """An error with its own status and code (`device_offline`, `camera_auth`, …)."""

    def __init__(self, status: int, code: str, message_ro: str) -> None:
        super().__init__(message_ro)
        self.status = status
        self.code = code


def _offline() -> SetupError:
    return SetupError(409, "device_offline", DEVICE_OFFLINE_RO)


def _edge(svc: Services) -> EdgeAsk:
    if svc.edge_requests is None:
        raise Unavailable(NO_EDGE_LINK_RO)
    return svc.edge_requests


async def _ask(
    svc: Services, device: str, kind: RequestKind, timeout_s: float, source: str | None = None
) -> EdgeReply:
    try:
        reply = await _edge(svc).ask(device, kind, source=source, timeout_s=timeout_s)
    except EdgeTimeout:
        raise SetupError(504, "device_timeout", DEVICE_TIMEOUT_RO) from None
    except EdgeUnreachable:
        raise Unavailable(NO_BROKER_RO) from None
    if not reply.ok and reply.error in (None, "failed"):
        raise SetupError(502, "device_error", DEVICE_ERROR_RO)
    return reply


def _serves_jobs(device: Device, sources: list[str]) -> bool:
    """A device that can test a camera on the venue network: not the clip runner, and not a
    cloud vision worker (every camera of it is a cloud camera)."""
    if is_upload_device(device.id):
        return False
    return not sources or not all(s.startswith(CLOUD_SOURCE) for s in sources)


# -- discovery ------------------------------------------------------------------------------


class FoundCamera(BaseModel):
    ip: str
    port: int
    brand: str
    model: str | None
    name: str | None
    onvif: bool
    rtsp_paths: list[str]
    already_added: bool
    """A camera of this location already uses this IP."""


class DiscoverOut(BaseModel):
    cameras: list[FoundCamera]


@router.post("/devices/{device_id}/discover")
async def discover_cameras(
    device_id: str,
    s: SessionDep,
    svc: ServicesDep,
    p: CurrentUser,
    location_id: Annotated[str | None, Query(max_length=64)] = None,
) -> DiscoverOut:
    """The IP cameras the device finds on its network (devices.manage at its location)."""
    loc = await device_location(s, device_id)
    if location_id is not None and loc != location_id:
        loc = None  # not a device of the location the dashboard is on
    loc, _role = authorize_at(p, DEVICES_MANAGE, loc, f"Dispozitivul {device_id} nu există.")
    device = await DeviceRepository(s).get(device_id)
    if device is None or device.state != "online":
        raise _offline()
    _edge(svc)
    taken = {
        url_host(row.source) for row in await CameraRepository(s).list_all(location_id=loc)
    } - {None}
    await s.close()  # the edge may take seconds: do not hold a connection meanwhile
    reply = await _ask(svc, device_id, "discover_cameras", DISCOVER_TIMEOUT_S)
    return DiscoverOut(
        cameras=[
            FoundCamera(**c.model_dump(), already_added=c.ip.lower() in taken)
            for c in reply.cameras
        ]
    )


# -- camera test ----------------------------------------------------------------------------


class CameraTestIn(BaseModel):
    source: str | None = Field(default=None, max_length=2048)
    """The camera URL to test. With `camera_id`, `***` in it stands for the stored password."""
    camera_id: str | None = Field(default=None, pattern=ID_PATTERN)
    """Test this saved camera, with its stored source (password included)."""
    device: str | None = Field(default=None, pattern=ID_PATTERN)
    """The edge device that tests it; default: the camera's device, else the location's only
    online device."""


FRAME_AT_HEADER = "X-Frame-At"
FRAME_SIZE_HEADER = "X-Frame-Size"


async def _source(s: SessionDep, loc: str, data: CameraTestIn) -> tuple[str, str | None]:
    """(the source to test, the saved camera's device if any)."""
    if data.camera_id is None:
        if not data.source:
            raise Invalid(NO_SOURCE_RO)
        if is_masked(data.source):
            raise Invalid(MASKED_RO)
        return data.source, None
    if await camera_location(s, data.camera_id) != loc:
        raise NotFound(f"Camera {data.camera_id} nu există.")
    row = await CameraRepository(s).get(data.camera_id)
    if row is None:
        raise NotFound(f"Camera {data.camera_id} nu există.")
    source = data.source or row.source
    if is_masked(source):
        try:
            source = restore_masked(source, row.source)
        except MaskedWithoutPassword:
            raise Invalid(MASKED_RO) from None
    return source, row.device_id


async def _device(s: SessionDep, loc: str, wanted: str | None, camera_device: str | None) -> str:
    devices = DeviceRepository(s)
    chosen = wanted or camera_device
    if chosen is not None:
        device = await devices.get(chosen)
        if device is None or device.site_id != loc:
            raise NotFound(f"Dispozitivul {chosen} nu există.")
        if device.state != "online":
            raise _offline()
        return chosen
    cameras = await CameraRepository(s).list_all(location_id=loc)
    candidates = [
        d.id
        for d in await devices.list_all(site_id=loc)
        if d.state == "online"
        and _serves_jobs(d, [c.source for c in cameras if c.device_id == d.id])
    ]
    if not candidates:
        raise _offline()
    if len(candidates) > 1:
        raise SetupError(422, "device_required", DEVICE_REQUIRED_RO)
    return candidates[0]


def _camera_error(code: str, source: str) -> SetupError:
    if code == "camera_auth":
        path = source.split("?", 1)[0]
        tapo = path.rstrip("/").endswith(TAPO_PATHS)
        return SetupError(422, code, CAMERA_AUTH_RO + (TAPO_AUTH_HINT_RO if tapo else ""))
    if code == "camera_unreachable":
        return SetupError(422, code, CAMERA_UNREACHABLE_RO)
    if code == "camera_no_stream":
        return SetupError(422, code, CAMERA_NO_STREAM_RO)
    return SetupError(422, "invalid", BAD_SOURCE_RO)  # bad_request: the edge refused the URL


@router.post(
    "/cameras/test",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
)
async def test_camera(
    data: CameraTestIn,
    s: SessionDep,
    svc: ServicesDep,
    access: Annotated[Access, Depends(require(DEVICES_MANAGE))],
) -> Response:
    """One face-blurred still of a camera, taken by an edge device of the location: 200
    `image/jpeg` with `X-Frame-At` (ISO 8601) and `X-Frame-Size` (`WxH` of the stream)."""
    _edge(svc)
    loc = access.location_id
    source, camera_device = await _source(s, loc, data)
    if not source.lower().startswith(LIVE_SCHEMES) or url_host(source) is None:
        raise Invalid(BAD_SOURCE_RO)
    device = await _device(s, loc, data.device, camera_device)
    await s.close()  # the edge may take seconds: do not hold a connection meanwhile
    reply = await _ask(svc, device, "test_camera", TEST_TIMEOUT_S, source=source)
    if not reply.ok or not reply.jpeg_b64:
        raise _camera_error(reply.error or "camera_no_stream", source)
    headers = {"Cache-Control": "no-store"}
    if reply.frame_at is not None:
        headers[FRAME_AT_HEADER] = reply.frame_at.isoformat()
    if reply.width and reply.height:
        headers[FRAME_SIZE_HEADER] = f"{reply.width}x{reply.height}"
    return Response(base64.b64decode(reply.jpeg_b64), media_type="image/jpeg", headers=headers)
