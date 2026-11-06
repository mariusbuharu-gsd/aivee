"""Which location a resource belongs to, so routes can authorize by resource id.

Everything hangs off a device: device.site_id is the location; cameras belong to a device;
rules to a camera; events and suggestions carry the device that produced them (events fall
back to their camera's device).
"""

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.auth.permissions import Role
from aivee_api.auth.principal import Principal
from aivee_api.db.models import Camera, Device, EventRow, RuleRow, SuggestionRow
from aivee_api.errors import NotFound


def devices_at(location_id: str) -> Select[str]:
    return select(Device.id).where(Device.site_id == location_id)


def cameras_at(location_id: str) -> Select[str]:
    return select(Camera.id).where(Camera.device_id.in_(devices_at(location_id)))


def events_at(location_id: str) -> Select[EventRow]:
    return select(EventRow).where(
        or_(
            EventRow.device_id.in_(devices_at(location_id)),
            EventRow.camera_id.in_(cameras_at(location_id)),
        )
    )


async def camera_ids_at(s: AsyncSession, location_id: str) -> set[str]:
    return set(await s.scalars(cameras_at(location_id)))


async def device_location(s: AsyncSession, device_id: str | None) -> str | None:
    if not device_id:
        return None
    return await s.scalar(select(Device.site_id).where(Device.id == device_id))


async def camera_location(s: AsyncSession, camera_id: str) -> str | None:
    return await s.scalar(
        select(Device.site_id)
        .join(Camera, Camera.device_id == Device.id)
        .where(Camera.id == camera_id)
    )


async def rule_location(s: AsyncSession, rule_id: str) -> str | None:
    camera_id = await s.scalar(select(RuleRow.camera_id).where(RuleRow.id == rule_id))
    return await camera_location(s, camera_id) if camera_id else None


async def event_location(s: AsyncSession, event_id: str) -> str | None:
    row = await s.scalar(select(EventRow).where(EventRow.event_id == event_id))
    if row is None:
        return None
    return await device_location(s, row.device_id) or await camera_location(s, row.camera_id)


async def suggestion_location(s: AsyncSession, suggestion_id: str) -> str | None:
    row = await s.scalar(select(SuggestionRow).where(SuggestionRow.suggestion_id == suggestion_id))
    if row is None:
        return None
    return await device_location(s, row.device_id) or await camera_location(s, row.camera_id)


def authorize_at(
    p: Principal, permission: str, location_id: str | None, not_found_ro: str
) -> tuple[str, Role]:
    """Like `Principal.authorize`, but a resource outside the caller's locations (or with no
    location at all) is reported as the resource itself not existing."""
    if location_id is None or p.role_at(location_id) is None:
        raise NotFound(not_found_ro)
    return location_id, p.authorize(permission, location_id)


async def authorize_camera(s: AsyncSession, p: Principal, permission: str, camera_id: str) -> str:
    loc = await camera_location(s, camera_id)
    return authorize_at(p, permission, loc, f"Camera {camera_id} nu există.")[0]


async def authorize_rule(s: AsyncSession, p: Principal, permission: str, rule_id: str) -> str:
    loc = await rule_location(s, rule_id)
    return authorize_at(p, permission, loc, f"Regula {rule_id} nu există.")[0]
