from fastapi import APIRouter, Path, status

from aivee_api.auth.deps import CurrentUser
from aivee_api.deps import SessionDep
from aivee_api.locations.schemas import (
    SAFE_ID,
    LocationIn,
    LocationOut,
    LocationPatch,
    MemberOut,
    MemberPatch,
)
from aivee_api.locations.service import LocationService, MemberService

router = APIRouter(prefix="/api/locations", tags=["locations"])

LocationId = Path(pattern=SAFE_ID)


@router.get("")
async def list_locations(s: SessionDep, p: CurrentUser) -> list[LocationOut]:
    """Every location the caller can see (owner: all of the organization)."""
    return await LocationService(s, p).visible()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_location(data: LocationIn, s: SessionDep, p: CurrentUser) -> LocationOut:
    return await LocationService(s, p).create(data)


@router.patch("/{location_id}")
async def update_location(
    patch: LocationPatch, s: SessionDep, p: CurrentUser, location_id: str = LocationId
) -> LocationOut:
    return await LocationService(s, p).update(location_id, patch)


@router.delete("/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_location(s: SessionDep, p: CurrentUser, location_id: str = LocationId) -> None:
    await LocationService(s, p).delete(location_id)


@router.get("/{location_id}/members")
async def list_members(
    s: SessionDep, p: CurrentUser, location_id: str = LocationId
) -> list[MemberOut]:
    return await MemberService(s, p).list(location_id)


@router.patch("/{location_id}/members/{user_id}")
async def set_member_role(
    user_id: str, data: MemberPatch, s: SessionDep, p: CurrentUser, location_id: str = LocationId
) -> MemberOut:
    return await MemberService(s, p).set_role(location_id, user_id, data.role)


@router.delete("/{location_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    user_id: str, s: SessionDep, p: CurrentUser, location_id: str = LocationId
) -> None:
    await MemberService(s, p).remove(location_id, user_id)
