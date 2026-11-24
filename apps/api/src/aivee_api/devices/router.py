from datetime import datetime
from typing import Annotated, Any

from aivee_contracts.events import CameraStreamHealth, DeviceStatus
from fastapi import APIRouter, Depends
from pydantic import ValidationError

from aivee_api.auth.deps import Access, require
from aivee_api.auth.permissions import ALERTS_VIEW
from aivee_api.db.repositories import DeviceRepository
from aivee_api.deps import SessionDep
from aivee_api.videos.kind import is_upload_device

router = APIRouter(prefix="/api/devices", tags=["devices"])


class DeviceOut(DeviceStatus):
    site: str
    last_seen: datetime | None = None


def _valid_health(rows: list[dict[str, Any]]) -> list[CameraStreamHealth]:
    """The stored camera health; an entry that no longer validates is left out."""
    out: list[CameraStreamHealth] = []
    for row in rows or []:
        try:
            out.append(CameraStreamHealth.model_validate(row))
        except ValidationError:
            continue
    return out


@router.get("")
async def list_devices(
    s: SessionDep, access: Annotated[Access, Depends(require(ALERTS_VIEW))]
) -> list[DeviceOut]:
    return [
        DeviceOut(
            device=d.id,
            state=d.state,  # type: ignore[arg-type]  # CHECK constraint keeps it valid
            version=d.version,
            cameras=list(d.cameras),
            camera_health=_valid_health(d.camera_health),
            site=d.site_id,
            last_seen=d.last_seen,
        )
        for d in await DeviceRepository(s).list_all(site_id=access.location_id)
        if not is_upload_device(d.id)
    ]
