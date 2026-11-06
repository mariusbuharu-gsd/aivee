import uuid
from collections.abc import Sequence

from aivee_contracts.geometry import CameraConfig, Zone
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.cameras.schemas import CameraIn, CameraOut, CameraPatch
from aivee_api.db.models import Camera
from aivee_api.db.repositories import CameraRepository, DeviceRepository, camera_config
from aivee_api.edge.sync import EdgeSync
from aivee_api.errors import Conflict, Invalid, NotFound


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
    """A camera belongs to the device given on create, else the API's DEVICE (env)."""

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
        device = data.device or self._sync.device
        await self._devices.ensure_device(self._sync.site, device)
        if not await self._cameras.insert(camera, device_id=device):
            raise Conflict(
                f"Există deja o cameră cu id-ul „{camera.id}”. "
                "Alege alt id sau modifică camera existentă."
            )
        await self._s.commit()
        await self._sync.publish_config()
        return await self.get(camera.id)

    async def update(self, camera_id: str, patch: CameraPatch) -> CameraOut:
        before = await self.get(camera_id)
        if patch.device:
            await self._devices.ensure_device(self._sync.site, patch.device)
        await self._cameras.update(
            camera_id, name=patch.name, source=patch.source, device_id=patch.device
        )
        await self._s.commit()
        await self._sync.publish_config()
        if patch.device and patch.device != before.device:
            await self._sync.publish_rules()  # the camera's rules move with it
        return await self.get(camera_id)

    async def zones(self, camera_id: str) -> list[Zone]:
        return (await self.get(camera_id)).zones

    async def set_zones(self, camera_id: str, zones: list[Zone]) -> list[Zone]:
        await self.get(camera_id)
        check_unique_zone_ids(zones)
        await self._cameras.set_zones(camera_id, zones)
        await self._s.commit()
        await self._sync.publish_config()
        return zones
