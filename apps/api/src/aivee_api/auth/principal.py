"""Who is calling and what they may do where. Loaded once per request from the session."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.accounts.models import Membership, Organization, SessionRow, User
from aivee_api.audit.repository import Actor
from aivee_api.auth.permissions import Role, has_permission
from aivee_api.auth.tokens import hash_token, should_extend
from aivee_api.db.models import Site
from aivee_api.errors import Forbidden, NotFound

NO_LOCATION = "Locația nu există."
FORBIDDEN = "Nu aveți dreptul să faceți această acțiune."


@dataclass(frozen=True)
class LocationAccess:
    id: str
    name: str
    type: str
    role: Role


@dataclass(frozen=True)
class Principal:
    user_id: str
    name: str
    email: str
    org_id: str
    org_name: str
    is_owner: bool
    locations: tuple[LocationAccess, ...] = ()
    _roles: dict[str, Role] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        self._roles.update({loc.id: loc.role for loc in self.locations})

    @property
    def actor(self) -> Actor:
        return Actor("user", self.user_id, self.name)

    def role_at(self, location_id: str) -> Role | None:
        return self._roles.get(location_id)

    def location(self, location_id: str) -> LocationAccess | None:
        return next((loc for loc in self.locations if loc.id == location_id), None)

    def locations_with(self, permission: str) -> list[str]:
        return [loc.id for loc in self.locations if has_permission(loc.role, permission)]

    def can(self, permission: str, location_id: str) -> bool:
        role = self.role_at(location_id)
        return role is not None and has_permission(role, permission)

    def authorize(self, permission: str, location_id: str) -> Role:
        """The caller's role at the location. Another org's / location's data does not exist
        for the caller (404); a visible location without the permission is 403."""
        role = self.role_at(location_id)
        if role is None:
            raise NotFound(NO_LOCATION)
        if not has_permission(role, permission):
            raise Forbidden(FORBIDDEN)
        return role

    def default_location(self) -> str:
        if not self.locations:
            raise NotFound("Nu aveți acces la nicio locație.")
        return self.locations[0].id


async def load_principal(s: AsyncSession, user: User) -> Principal:
    org = await s.get(Organization, user.org_id)
    if user.is_owner:
        rows = await s.scalars(
            select(Site).where(Site.org_id == user.org_id).order_by(Site.created_at, Site.id)
        )
        locations = tuple(LocationAccess(r.id, r.name, r.type, "owner") for r in rows)
    else:
        result = await s.execute(
            select(Site, Membership.role)
            .join(Membership, Membership.location_id == Site.id)
            .where(Membership.user_id == user.id, Site.org_id == user.org_id)
            .order_by(Site.created_at, Site.id)
        )
        locations = tuple(
            LocationAccess(site.id, site.name, site.type, role)  # type: ignore[arg-type]
            for site, role in result
        )
    return Principal(
        user_id=user.id,
        name=user.name,
        email=user.email,
        org_id=user.org_id,
        org_name=org.name if org else "",
        is_owner=user.is_owner,
        locations=locations,
    )


@dataclass(frozen=True)
class SessionLookup:
    principal: Principal
    extended_until: datetime | None
    """Set when the sliding expiry moved: the cookie must be re-sent."""


async def principal_for_token(
    s: AsyncSession, token: str | None, ttl: timedelta, now: datetime | None = None
) -> SessionLookup | None:
    if not token:
        return None
    now = now or datetime.now(UTC)
    row = await s.get(SessionRow, hash_token(token))
    if row is None or row.expires_at <= now:
        return None
    user = await s.get(User, row.user_id)
    if user is None:
        return None
    extended: datetime | None = None
    if should_extend(row.expires_at, now, ttl):
        extended = now + ttl
        await s.execute(
            update(SessionRow)
            .where(SessionRow.token_hash == row.token_hash)
            .values(expires_at=extended)
        )
        await s.commit()
    return SessionLookup(await load_principal(s, user), extended)
