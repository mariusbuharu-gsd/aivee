from typing import Literal

from pydantic import BaseModel, Field

from aivee_api.db.models import Site

LocationType = Literal["restaurant", "terrace", "event", "shop", "other"]
SAFE_ID = r"^[A-Za-z0-9_-]{1,64}$"  # the location id is the MQTT <site> segment


class LocationIn(BaseModel):
    id: str = Field(pattern=SAFE_ID)
    name: str = Field(min_length=1, max_length=200)
    type: LocationType = "restaurant"
    telegram_chat_id: str | None = Field(default=None, max_length=64)


class LocationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    type: LocationType | None = None
    telegram_chat_id: str | None = Field(default=None, max_length=64)


class LocationOut(BaseModel):
    id: str
    name: str
    type: str
    telegram_chat_id: str | None = None


class LocationSummary(LocationOut):
    """`GET /api/locations`: a location with its live cameras (uploaded clips not counted)."""

    cameras_total: int = 0
    cameras_online: int = 0
    """Cameras whose device is online."""


def location_out(row: Site) -> LocationOut:
    return LocationOut(
        id=row.id, name=row.name, type=row.type, telegram_chat_id=row.telegram_chat_id
    )


def location_json(row: Site) -> dict[str, str | None]:
    """The audited before/after of a location."""
    return location_out(row).model_dump()


class MemberOut(BaseModel):
    user_id: str
    name: str
    email: str
    role: Literal["owner", "manager", "staff"]
    push_enabled: bool = False
    """The member has a Web Push subscription (a phone or browser that gets the alerts)."""


class MemberPatch(BaseModel):
    role: Literal["manager", "staff"]
