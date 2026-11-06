from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from aivee_api.audit.record import record
from aivee_api.audit.repository import Target
from aivee_api.auth.deps import Access, CurrentUser, require
from aivee_api.auth.permissions import ALERTS_VIEW, DEVICES_MANAGE
from aivee_api.auth.principal import Principal
from aivee_api.auth.scope import authorize_at, authorize_camera, camera_ids_at, device_location
from aivee_api.cameras.schemas import CameraIn, CameraOut, CameraPatch
from aivee_api.cameras.service import CameraService
from aivee_api.deps import ServicesDep, SessionDep
from aivee_api.errors import Invalid

router = APIRouter(prefix="/api/cameras", tags=["cameras"])

NO_DEVICE_HERE = "Locația nu are un dispozitiv conectat la acest server."


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
    ids = await camera_ids_at(s, access.location_id)
    return [c for c in await CameraService(s, svc.sync).list_all() if c.id in ids]


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
    await _check_device(s, loc, data.device or svc.sync.device)
    camera = await CameraService(s, svc.sync).create(data)
    await _record(s, p, "camera.created", loc, camera, after=camera)
    return camera


@router.get("/{camera_id}")
async def get_camera(camera_id: str, s: SessionDep, svc: ServicesDep, p: CurrentUser) -> CameraOut:
    await authorize_camera(s, p, ALERTS_VIEW, camera_id)
    return await CameraService(s, svc.sync).get(camera_id)


@router.put("/{camera_id}")
@router.patch("/{camera_id}")
async def update_camera(
    camera_id: str, data: CameraPatch, s: SessionDep, svc: ServicesDep, p: CurrentUser
) -> CameraOut:
    """Change name, source and/or device; zones are kept (edit them through `/zones`)."""
    loc = await authorize_camera(s, p, DEVICES_MANAGE, camera_id)
    await _check_device(s, loc, data.device)
    service = CameraService(s, svc.sync)
    before = await service.get(camera_id)
    camera = await service.update(camera_id, data)
    await _record(s, p, "camera.updated", loc, camera, before=before, after=camera)
    return camera


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
        before=before.model_dump(mode="json") if before else None,
        after=after.model_dump(mode="json") if after else None,
    )
