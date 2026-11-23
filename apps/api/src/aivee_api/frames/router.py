"""Cloud mode over HTTPS (port 443 only): frames in from the connector, MJPEG out to the dashboard.

    POST /api/ingest/frames/{camera_id}   one JPEG, authenticated by one of:
                                          - Bearer <the camera's own push key> (S6,
                                            `aivee_api.frames.keys`);
                                          - HTTP Basic STREAM_PUBLISH_USER/PASSWORD, shared:
                                            only for a camera without a key, at a location
                                            claimed by an organisation;
                                          - the dashboard session ("Folosește telefonul ca
                                            cameră") with devices.manage, cloud cameras only
    GET  /api/cameras/{camera_id}/live.mjpg   session cookie, alerts.view on the camera's location

See `aivee_api.frames.store` (in memory, single replica, never on disk).
"""

import base64
import binascii
import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from aivee_contracts.topics import Topics
from fastapi import APIRouter, Depends, Path, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from aivee_api.auth.deps import COOKIE, CurrentUser, current_principal
from aivee_api.auth.permissions import ALERTS_VIEW, DEVICES_MANAGE
from aivee_api.auth.scope import authorize_camera
from aivee_api.cameras.schemas import ID_PATTERN
from aivee_api.db.models import Camera, Device, Site
from aivee_api.deps import ServicesDep
from aivee_api.errors import Conflict, NotFound, TooLarge, Unauthenticated, UnsupportedType
from aivee_api.frames.keys import bearer, key_matches
from aivee_api.frames.store import BOUNDARY, is_jpeg, mjpeg_stream
from aivee_api.settings import ApiSettings

router = APIRouter(tags=["frames"])

CameraId = Annotated[str, Path(pattern=ID_PATTERN)]


@dataclass(frozen=True)
class CameraTarget:
    """What frame ingest needs to know about a camera: where to relay, who owns it, its key."""

    topics: Topics
    org_id: str | None
    push_key_hash: str | None = None


CameraLookup = Callable[[str], Awaitable[CameraTarget | None]]

BAD_CREDENTIALS_RO = "Date de publicare greșite."
OWN_KEY_RO = "Camera aceasta are cheia ei de publicare."
TOO_LARGE_RO = "Cadrul e prea mare."
NOT_JPEG_RO = "Cadrul trebuie să fie JPEG."
NO_LIVE_RO = "Camera nu trimite imagini acum."
NOT_CLOUD_RO = "Camera aceasta nu primește imagini de la telefon."
CLOUD_SOURCE = "mqtt-frames://"


def is_cloud_source(camera_id: str, source: str) -> bool:
    """A cloud camera reads the frames pushed for it: `mqtt-frames://<its id>`."""
    return source == f"{CLOUD_SOURCE}{camera_id}"


def credentials_ok(header: str | None, settings: ApiSettings) -> bool:
    """HTTP Basic against the publish credentials, compared in constant time."""
    user, password = settings.stream_publish_user, settings.stream_publish_password
    if not user or not password or not header:
        return False
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        given_user, sep, given_password = base64.b64decode(encoded, validate=True).partition(b":")
    except (binascii.Error, ValueError):
        return False
    user_ok = hmac.compare_digest(given_user, user.encode())
    password_ok = hmac.compare_digest(given_password, password.encode())
    return bool(sep) and user_ok and password_ok


async def read_limited(request: Request, max_bytes: int) -> bytes:
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > max_bytes:
        raise TooLarge(TOO_LARGE_RO)
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > max_bytes:
            raise TooLarge(TOO_LARGE_RO)
    return bytes(body)


def get_camera_target(svc: ServicesDep) -> CameraLookup:
    """The camera's device topics, its location's organisation and its push key hash; None
    when the camera does not exist (or has no device)."""

    async def find(camera_id: str) -> CameraTarget | None:
        async with svc.sessions() as s:
            row = (
                await s.execute(
                    select(Device.site_id, Camera.device_id, Site.org_id, Camera.push_key_hash)
                    .join(Device, Device.id == Camera.device_id)
                    .outerjoin(Site, Site.id == Device.site_id)
                    .where(Camera.id == camera_id)
                )
            ).first()
        if row is None:
            return None
        site, device, org_id, key_hash = row
        return CameraTarget(Topics(site=site, device=device), org_id, key_hash)

    return find


async def authorize_session_push(
    request: Request, response: Response, svc: ServicesDep, camera_id: str
) -> None:
    """A logged-in user pushing from the phone page: devices.manage at the camera's location
    (404 elsewhere, 403 without it) and only onto a cloud camera (409 otherwise)."""
    p = await current_principal(request, response, svc)
    async with svc.sessions() as s:
        await authorize_camera(s, p, DEVICES_MANAGE, camera_id)
        source = await s.scalar(select(Camera.source).where(Camera.id == camera_id))
    if source is None or not is_cloud_source(camera_id, source):
        raise Conflict(NOT_CLOUD_RO)


@router.post("/api/ingest/frames/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def ingest_frame(
    camera_id: CameraId,
    request: Request,
    response: Response,
    svc: ServicesDep,
    lookup: Annotated[CameraLookup, Depends(get_camera_target)],
) -> None:
    """One JPEG from the connector or the phone page: kept as the camera's newest frame and
    relayed over MQTT (`Topics.frames`) to its vision worker. Auth, then size and type, then
    the camera. `Bearer` is the camera's own key; any other Authorization header is the
    shared Basic credential; without one, the session cookie."""
    header = request.headers.get("authorization")
    key = bearer(header)
    missing = f"Camera {camera_id} nu există."
    if key is not None:
        target = await lookup(camera_id)
        # An unknown camera answers like a wrong key: a key never tells which cameras exist.
        if target is None or not key_matches(key, target.push_key_hash):
            raise Unauthenticated(BAD_CREDENTIALS_RO)
    elif header is not None or COOKIE not in request.cookies:
        if not credentials_ok(header, svc.settings):
            raise Unauthenticated(BAD_CREDENTIALS_RO)
        target = await lookup(camera_id)
        if target is not None and target.push_key_hash:
            raise Unauthenticated(OWN_KEY_RO)
        if target is not None and target.org_id is None:
            # A location ingest created for an unknown device belongs to nobody yet.
            target = None
    else:
        await authorize_session_push(request, response, svc, camera_id)
        target = await lookup(camera_id)
    jpeg = await read_limited(request, svc.settings.frame_max_bytes)
    if not is_jpeg(jpeg):
        raise UnsupportedType(NOT_JPEG_RO)
    if target is None:
        raise NotFound(missing)
    svc.frames.put(camera_id, jpeg)
    await svc.frames.relay(target.topics.frames(camera_id), jpeg)


@router.get("/api/cameras/{camera_id}/live.mjpg", response_class=StreamingResponse)
async def live_mjpeg(
    camera_id: CameraId, request: Request, svc: ServicesDep, p: CurrentUser
) -> StreamingResponse:
    """MJPEG of the frames the connector posts, for a dashboard `<img>`; 404 while none came in
    the last seconds. Ends when the client goes away."""
    async with svc.sessions() as s:  # not a request-long session: the stream may run for hours
        await authorize_camera(s, p, ALERTS_VIEW, camera_id)
    if svc.frames.latest(camera_id) is None:
        raise NotFound(NO_LIVE_RO)
    return StreamingResponse(
        mjpeg_stream(
            svc.frames,
            camera_id,
            fps=svc.settings.live_fps,
            idle_s=svc.settings.live_idle_s,
            disconnected=request.is_disconnected,
        ),
        media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
