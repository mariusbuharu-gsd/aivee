import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aivee_contracts.events import CameraStreamHealth, StreamState
from aivee_contracts.geometry import CameraConfig, Zone
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.alerts.audit import AuditWriter, system_closed_entry
from aivee_api.alerts.repository import AlertRepository
from aivee_api.cameras.masking import MaskedWithoutPassword, is_masked, mask_source, restore_masked
from aivee_api.cameras.schemas import CameraIn, CameraOut, CameraPatch
from aivee_api.db.models import Camera, Device
from aivee_api.db.repositories import CameraRepository, DeviceRepository, camera_config
from aivee_api.edge.sync import EdgeSync
from aivee_api.errors import Conflict, Invalid, NotFound

MASKED_NEW_RO = "Scrie parola camerei: „***” ține doar locul unei parole deja salvate."


@dataclass(frozen=True)
class CameraStream:
    state: StreamState | None
    last_frame_at: datetime | None
    online: bool


def camera_stream(
    camera_id: str, device_state: str | None, health: Sequence[Mapping[str, Any]] | None
) -> CameraStream:
    """One camera's stream from its device's state (None: no device) and the device's stored
    `camera_health`. An offline device takes every camera down (keeping the last frame time
    known); an online one speaks per camera, None where it said nothing (or nothing valid)."""
    if device_state is None:
        return CameraStream(None, None, online=False)
    report = _report(camera_id, health)
    last_frame_at = report.last_frame_at if report else None
    if device_state != "online":
        return CameraStream("down", last_frame_at, online=False)
    state = report.state if report else None
    return CameraStream(state, last_frame_at, online=state != "down")


def _report(
    camera_id: str, health: Sequence[Mapping[str, Any]] | None
) -> CameraStreamHealth | None:
    for item in health or []:
        if item.get("camera_id") == camera_id:
            try:
                return CameraStreamHealth.model_validate(item)
            except ValidationError:
                return None
    return None


def _out(row: Camera, devices: Mapping[str, Device]) -> CameraOut:
    device = devices.get(row.device_id or "")
    stream = camera_stream(
        row.id, device.state if device else None, device.camera_health if device else None
    )
    config = camera_config(row)
    return CameraOut(
        **config.model_dump(exclude={"source"}),
        source=mask_source(config.source),
        device=row.device_id or "",
        online=stream.online,
        stream_state=stream.state,
        last_frame_at=stream.last_frame_at,
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

    async def _devices_by_id(self, location_id: str | None = None) -> dict[str, Device]:
        return {d.id: d for d in await self._devices.list_all(site_id=location_id)}

    async def list_all(self, location_id: str | None = None) -> list[CameraOut]:
        """Every camera, or (in the query) only those of one location."""
        devices = await self._devices_by_id(location_id)
        rows = await self._cameras.list_all(location_id=location_id)
        return [_out(r, devices) for r in rows]

    async def get(self, camera_id: str) -> CameraOut:
        row = await self._cameras.get(camera_id)
        if row is None:
            raise NotFound(f"Camera {camera_id} nu există.")
        device = await self._devices.get(row.device_id) if row.device_id else None
        return _out(row, {device.id: device} if device else {})

    async def create(self, data: CameraIn) -> CameraOut:
        check_unique_zone_ids(data.zones)
        if is_masked(data.source):
            raise Invalid(MASKED_NEW_RO)
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
        source = await self._unmasked(camera_id, patch.source)
        if patch.device:
            await self._devices.ensure_device(self._sync.site, patch.device)
        await self._cameras.update(
            camera_id, name=patch.name, source=source, device_id=patch.device
        )
        await self._s.commit()
        await self._sync.publish_config()
        if patch.device and patch.device != before.device:
            await self._sync.publish_rules()  # the camera's rules move with it
        return await self.get(camera_id)

    async def stored_source(self, camera_id: str) -> str:
        """The camera's real source, password included: only for the edge, never a response."""
        row = await self._cameras.get(camera_id)
        if row is None:
            raise NotFound(f"Camera {camera_id} nu există.")
        return row.source

    async def _unmasked(self, camera_id: str, source: str | None) -> str | None:
        """An edited source with `***` put back to the stored password (see `masking`)."""
        if source is None or not is_masked(source):
            return source
        try:
            return restore_masked(source, await self.stored_source(camera_id))
        except MaskedWithoutPassword:
            raise Invalid(MASKED_NEW_RO) from None

    async def delete(self, camera_id: str, audit: AuditWriter) -> CameraOut:
        """Delete the camera with its zones and rules; its open alerts are closed by the
        system (`camera_deleted`) in the same transaction, and the device's retained
        config and rules are republished so the edge drops the camera. Returns the
        camera as it was."""
        before = await self.get(camera_id)
        closed = await AlertRepository(self._s).close_open_for_camera(
            camera_id, datetime.now(UTC), "camera_deleted"
        )
        for view in closed:
            await audit.append(self._s, system_closed_entry(view, "camera_deleted"))
        await self._cameras.delete(camera_id)
        await self._s.commit()
        await self._sync.publish_config()
        await self._sync.publish_rules()
        return before

    async def zones(self, camera_id: str) -> list[Zone]:
        return (await self.get(camera_id)).zones

    async def set_zones(self, camera_id: str, zones: list[Zone]) -> list[Zone]:
        await self.get(camera_id)
        check_unique_zone_ids(zones)
        await self._cameras.set_zones(camera_id, zones)
        await self._s.commit()
        await self._sync.publish_config()
        return zones
