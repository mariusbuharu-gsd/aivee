"""Request/response bodies of /api/auth (the `Me` shape is the spec's TypeScript type)."""

from typing import Literal

from pydantic import BaseModel, Field

from aivee_api.auth.permissions import permissions_for
from aivee_api.auth.principal import Principal

RoleName = Literal["owner", "manager", "staff"]


class RegisterIn(BaseModel):
    org_name: str = Field(max_length=200)
    name: str = Field(max_length=200)
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


class MeUser(BaseModel):
    id: str
    name: str
    email: str


class MeOrg(BaseModel):
    id: str
    name: str


class MeLocation(BaseModel):
    id: str
    name: str
    type: str
    role: RoleName
    permissions: list[str]


class Me(BaseModel):
    user: MeUser
    org: MeOrg
    is_owner: bool
    locations: list[MeLocation]


def me_out(p: Principal) -> Me:
    return Me(
        user=MeUser(id=p.user_id, name=p.name, email=p.email),
        org=MeOrg(id=p.org_id, name=p.org_name),
        is_owner=p.is_owner,
        locations=[
            MeLocation(
                id=loc.id,
                name=loc.name,
                type=loc.type,
                role=loc.role,
                permissions=sorted(permissions_for(loc.role)),
            )
            for loc in p.locations
        ],
    )
