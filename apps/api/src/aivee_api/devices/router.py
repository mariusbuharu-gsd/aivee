from datetime import datetime

from aivee_contracts.events import DeviceStatus
from fastapi import APIRouter

from aivee_api.db.repositories import DeviceRepository
from aivee_api.deps import SessionDep

router = APIRouter(prefix="/api/devices", tags=["devices"])


class DeviceOut(DeviceStatus):
    site: str
    last_seen: datetime | None = None


@router.get("")
async def list_devices(s: SessionDep) -> list[DeviceOut]:
    return [
        DeviceOut(
            device=d.id,
            state=d.state,  # type: ignore[arg-type]  # CHECK constraint keeps it valid
            version=d.version,
            cameras=list(d.cameras),
            site=d.site_id,
            last_seen=d.last_seen,
        )
        for d in await DeviceRepository(s).list_all()
    ]
