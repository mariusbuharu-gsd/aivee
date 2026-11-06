from aivee_contracts.geometry import Zone
from fastapi import APIRouter
from pydantic import BaseModel

from aivee_api.audit.record import record
from aivee_api.audit.repository import Target
from aivee_api.auth.deps import CurrentUser
from aivee_api.auth.permissions import ALERTS_VIEW, DEVICES_MANAGE
from aivee_api.auth.scope import authorize_camera
from aivee_api.cameras.service import CameraService
from aivee_api.deps import ServicesDep, SessionDep
from aivee_api.zones.overlap import overlap_warnings_ro

router = APIRouter(prefix="/api/cameras/{camera_id}/zones", tags=["zones"])


class ZonesSaved(BaseModel):
    """`PUT ...?warnings=true`: the saved zones and what looks wrong with them (they are
    saved anyway), e.g. "Zonele «Masa 1» și «Masa 2» se suprapun"."""

    zones: list[Zone]
    warnings_ro: list[str]


@router.get("")
async def get_zones(camera_id: str, s: SessionDep, svc: ServicesDep, p: CurrentUser) -> list[Zone]:
    await authorize_camera(s, p, ALERTS_VIEW, camera_id)
    return await CameraService(s, svc.sync).zones(camera_id)


@router.put("")
async def put_zones(
    camera_id: str,
    zones: list[Zone],
    s: SessionDep,
    svc: ServicesDep,
    p: CurrentUser,
    warnings: bool = False,
) -> list[Zone] | ZonesSaved:
    """Replace every zone of the camera; the edge gets the full DeviceConfig (retained).

    Overlapping zones are accepted. With `?warnings=true` the response is `ZonesSaved`,
    naming each overlapping pair; without it, the plain list (what the dashboard reads)."""
    loc = await authorize_camera(s, p, DEVICES_MANAGE, camera_id)
    service = CameraService(s, svc.sync)
    camera = await service.get(camera_id)
    saved = await service.set_zones(camera_id, zones)
    await record(
        s,
        p,
        "zones.updated",
        location_id=loc,
        target=Target("camera", camera_id, camera.name or camera_id),
        before=[z.model_dump(mode="json") for z in camera.zones],
        after=[z.model_dump(mode="json") for z in saved],
    )
    if warnings:
        return ZonesSaved(zones=saved, warnings_ro=overlap_warnings_ro(saved))
    return saved
