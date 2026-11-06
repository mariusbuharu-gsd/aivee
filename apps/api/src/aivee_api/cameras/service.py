import uuid
from collections.abc import Sequence

from aivee_contracts.geometry import CameraConfig, Zone
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.cameras.schemas import CameraIn, CameraOut
from aivee_api.db.models import Camera
from aivee_api.db.repositories import CameraRepository, DeviceRepository, camera_config
from aivee_api.edge.sync import EdgeSync
from aivee_api.errors import Invalid, NotFound


def _out(row: Camera, online_devices: set[str]) -> CameraOut:
    device = row.device_id or ""
    return CameraOut(
        **camera_config(row).model_dump(), device=device, online=device in online_devices
    )


def check_unique_zone_ids(zones: Sequence[Zone]) -> None:
    ids = [z.id for z in zones]
    if len(ids) != len(set(ids)):
        raise Invalid("Fiecare zonă trebuie să aibă un id unic.")


class CameraService:
    """Cameras created here belong to the API's configured device (SITE/DEVICE env)."""

    def __init__(self, session: AsyncSession, sync: EdgeSync) -> None:
        self._s = session
        self._cameras = CameraRepository(session)
        self._devices = DeviceRepository(session)
        self._sync = sync

    async def _online(self) -> set[str]:
        return {d.id for d in await self._devices.list_all() if d.state == "online"}

    async def list_all(self) -> list[CameraOut]:
        online = await self._online()
        return [_out(r, online) for r in await self._cameras.list_all()]

    async def get(self, camera_id: str) -> CameraOut:
        row = await self._cameras.get(camera_id)
        if row is None:
            raise NotFound(f"Camera {camera_id} nu există.")
        return _out(row, await self._online())

    async def create(self, data: CameraIn) -> CameraOut:
        check_unique_zone_ids(data.zones)
        camera = CameraConfig(
            id=data.id or f"cam-{uuid.uuid4().hex[:8]}",
            name=data.name,
            source=data.source,
            zones=data.zones,
        )
        await self._devices.ensure_device(self._sync.site, self._sync.device)
        await self._cameras.upsert(camera, device_id=self._sync.device)
        await self._s.commit()
        await self._sync.publish_config()
        return await self.get(camera.id)

    async def zones(self, camera_id: str) -> list[Zone]:
        return (await self.get(camera_id)).zones

    async def set_zones(self, camera_id: str, zones: list[Zone]) -> list[Zone]:
        await self.get(camera_id)
        check_unique_zone_ids(zones)
        await self._cameras.set_zones(camera_id, zones)
        await self._s.commit()
        await self._sync.publish_config()
        return zones
