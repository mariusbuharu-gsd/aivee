from fastapi import APIRouter, status

from aivee_api.cameras.schemas import CameraIn, CameraOut
from aivee_api.cameras.service import CameraService
from aivee_api.deps import ServicesDep, SessionDep

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


@router.get("")
async def list_cameras(s: SessionDep, svc: ServicesDep) -> list[CameraOut]:
    return await CameraService(s, svc.sync).list_all()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_camera(data: CameraIn, s: SessionDep, svc: ServicesDep) -> CameraOut:
    return await CameraService(s, svc.sync).create(data)


@router.get("/{camera_id}")
async def get_camera(camera_id: str, s: SessionDep, svc: ServicesDep) -> CameraOut:
    return await CameraService(s, svc.sync).get(camera_id)
