from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import update

from aivee_api.alerts.audit import AuditWriter, get_audit_writer
from aivee_api.audit.record import record
from aivee_api.audit.repository import Target
from aivee_api.auth.deps import Access, CurrentUser, require
from aivee_api.auth.permissions import ALERTS_VIEW, DEVICES_MANAGE
from aivee_api.auth.principal import Principal
from aivee_api.auth.scope import authorize_at, authorize_camera, device_location
from aivee_api.cameras.frame import latest_frame
from aivee_api.cameras.schemas import CameraIn, CameraOut, CameraPatch
from aivee_api.cameras.service import CameraService
from aivee_api.db.models import Camera
from aivee_api.deps import ServicesDep, SessionDep
from aivee_api.errors import Invalid, NotFound
from aivee_api.frames.keys import key_hash, new_key
from aivee_api.videos.kind import is_upload_camera, is_upload_device

router = APIRouter(prefix="/api/cameras", tags=["cameras"])

NO_DEVICE_HERE = "Locația nu are un dispozitiv conectat la acest server."
RESERVED_RO = "Id-urile care încep cu „video-” sau „upload-” sunt rezervate analizei video."


async def _check_device(s: SessionDep, loc: str, device: str | None) -> None:
    """A camera may only be attached to a device of its own location."""
    if device is None:
        return
    current = await device_location(s, device)
    if current is not None and current != loc:
        raise Invalid(f"Dispozitivul {device} aparține altei locații.")


@router.get("")
async def list_cameras(
    s: SessionDep, svc: ServicesDep, access: Annotated[Access, Depends(require(ALERTS_VIEW))]
) -> list[CameraOut]:
    cameras = await CameraService(s, svc.sync).list_all(access.location_id)
    # Uploaded clips' virtual cameras live on the Analiză video page, not among cameras.
    return [c for c in cameras if not is_upload_device(c.device)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_camera(
    data: CameraIn,
    s: SessionDep,
    svc: ServicesDep,
    p: CurrentUser,
    location_id: Annotated[str | None, Query(max_length=64)] = None,
) -> CameraOut:
    """New cameras go to the location of the API's edge link (SITE)."""
    loc = location_id or svc.sync.site
    authorize_at(p, DEVICES_MANAGE, loc, "Locația nu există.")
    if loc != svc.sync.site:
        raise Invalid(NO_DEVICE_HERE)
    if is_upload_camera(data.id) or is_upload_device(data.device):
        raise Invalid(RESERVED_RO)
    await _check_device(s, loc, data.device or svc.sync.device)
    camera = await CameraService(s, svc.sync).create(data)
    await _record(s, p, "camera.created", loc, camera, after=camera)
    return camera


@router.get("/{camera_id}")
async def get_camera(camera_id: str, s: SessionDep, svc: ServicesDep, p: CurrentUser) -> CameraOut:
    await authorize_camera(s, p, ALERTS_VIEW, camera_id)
    return await CameraService(s, svc.sync).get(camera_id)


FRAME_AT_HEADER = "X-Frame-At"
NO_FRAME_RO = "Nu există încă o imagine de la această cameră."


@router.get("/{camera_id}/frame", response_class=FileResponse)
async def get_camera_frame(
    camera_id: str, s: SessionDep, svc: ServicesDep, p: CurrentUser
) -> FileResponse:
    """The newest face-blurred still of the camera (alerts.view), its time in `X-Frame-At`
    (ISO 8601). 404 until the camera has sent one. See `aivee_api.cameras.frame`."""
    await authorize_camera(s, p, ALERTS_VIEW, camera_id)
    frame = await latest_frame(s, svc.settings.snapshot_dir, camera_id)
    if frame is None:
        raise NotFound(NO_FRAME_RO)
    return FileResponse(
        frame.path,
        media_type="image/jpeg",
        headers={FRAME_AT_HEADER: frame.at.isoformat(), "Cache-Control": "no-store"},
    )


class PushKeyOut(BaseModel):
    camera_id: str
    key: str
    """Shown once: the connector's CLOUD_PUSH_KEY. Only its sha256 is stored."""


@router.post("/{camera_id}/push-key", status_code=status.HTTP_201_CREATED)
async def create_push_key(camera_id: str, s: SessionDep, p: CurrentUser) -> PushKeyOut:
    """A new frame-ingest key for this camera (devices.manage); the previous one stops working,
    and so does the shared STREAM_PUBLISH_USER/PASSWORD for this camera (S6)."""
    loc = await authorize_camera(s, p, DEVICES_MANAGE, camera_id)
    key = new_key()
    await s.execute(
        update(Camera).where(Camera.id == camera_id).values(push_key_hash=key_hash(key))
    )
    await record(
        s,
        p,
        "camera.push_key_created",
        location_id=loc,
        target=Target("camera", camera_id, camera_id),
    )
    return PushKeyOut(camera_id=camera_id, key=key)


@router.put("/{camera_id}")
@router.patch("/{camera_id}")
async def update_camera(
    camera_id: str, data: CameraPatch, s: SessionDep, svc: ServicesDep, p: CurrentUser
) -> CameraOut:
    """Change name, source and/or device; zones are kept (edit them through `/zones`)."""
    loc = await authorize_camera(s, p, DEVICES_MANAGE, camera_id)
    if is_upload_device(data.device):
        raise Invalid(RESERVED_RO)
    await _check_device(s, loc, data.device)
    service = CameraService(s, svc.sync)
    before = await service.get(camera_id)
    camera = await service.update(camera_id, data)
    await _record(s, p, "camera.updated", loc, camera, before=before, after=camera)
    return camera


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(
    camera_id: str,
    s: SessionDep,
    svc: ServicesDep,
    p: CurrentUser,
    audit: Annotated[AuditWriter, Depends(get_audit_writer)],
) -> None:
    """Zones and rules go with the camera; its events and alerts stay in the history."""
    loc = await authorize_camera(s, p, DEVICES_MANAGE, camera_id)
    before = await CameraService(s, svc.sync).delete(camera_id, audit)
    await _record(s, p, "camera.deleted", loc, before, before=before)


async def _record(
    s: SessionDep,
    p: Principal,
    kind: str,
    loc: str,
    camera: CameraOut,
    before: CameraOut | None = None,
    after: CameraOut | None = None,
) -> None:
    await record(
        s,
        p,
        kind,
        location_id=loc,
        target=Target("camera", camera.id, camera.name or camera.id),
        before=before.model_dump(mode="json", exclude=LIVE_FIELDS) if before else None,
        after=after.model_dump(mode="json", exclude=LIVE_FIELDS) if after else None,
    )


LIVE_FIELDS = {"stream_state", "last_frame_at"}
"""What the edge reports, not what the user changed: kept out of the audit entries."""
