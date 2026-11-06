from aivee_contracts.geometry import Zone
from fastapi import APIRouter

from aivee_api.cameras.service import CameraService
from aivee_api.deps import ServicesDep, SessionDep

router = APIRouter(prefix="/api/cameras/{camera_id}/zones", tags=["zones"])


@router.get("")
async def get_zones(camera_id: str, s: SessionDep, svc: ServicesDep) -> list[Zone]:
    return await CameraService(s, svc.sync).zones(camera_id)


@router.put("")
async def put_zones(
    camera_id: str, zones: list[Zone], s: SessionDep, svc: ServicesDep
) -> list[Zone]:
    """Replace every zone of the camera; the edge gets the full DeviceConfig (retained)."""
    return await CameraService(s, svc.sync).set_zones(camera_id, zones)
