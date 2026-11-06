"""Locations of an organization and their members (users.manage, locations.manage)."""

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.accounts.models import Membership, User
from aivee_api.audit.repository import AuditRepository, Target
from aivee_api.auth.permissions import (
    LOCATIONS_MANAGE,
    USERS_MANAGE,
    MemberRole,
    Role,
    can_assign,
)
from aivee_api.auth.principal import FORBIDDEN, NO_LOCATION, Principal
from aivee_api.db.models import Camera, Device, PushSubscriptionRow, Site
from aivee_api.errors import Conflict, Forbidden, NotFound
from aivee_api.locations.schemas import (
    LocationIn,
    LocationOut,
    LocationPatch,
    LocationSummary,
    MemberOut,
    location_json,
    location_out,
)
from aivee_api.videos.kind import not_upload

NO_MEMBER = "Utilizatorul nu există."


async def camera_counts(s: AsyncSession, location_ids: list[str]) -> dict[str, tuple[int, int]]:
    """location id → (cameras, cameras whose device is online); uploaded clips left out."""
    if not location_ids:
        return {}
    online = func.count().filter(Device.state == "online")
    rows = await s.execute(
        select(Device.site_id, func.count(), online)
        .join(Camera, Camera.device_id == Device.id)
        .where(Device.site_id.in_(location_ids), not_upload(Device.id, Camera.id))
        .group_by(Device.site_id)
    )
    return {site: (total, on) for site, total, on in rows.all()}


async def push_users(s: AsyncSession, user_ids: list[str]) -> set[str]:
    """The users among `user_ids` with at least one Web Push subscription."""
    if not user_ids:
        return set()
    found = await s.scalars(
        select(PushSubscriptionRow.user_id)
        .where(PushSubscriptionRow.user_id.in_(user_ids))
        .distinct()
    )
    return {u for u in found if u is not None}


class LocationService:
    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self._s = session
        self._p = principal
        self._audit = AuditRepository(session)

    async def _row(self, location_id: str) -> Site:
        row = await self._s.get(Site, location_id)
        if row is None or row.org_id != self._p.org_id:
            raise NotFound(NO_LOCATION)
        return row

    async def visible(self) -> list[LocationSummary]:
        ids = [loc.id for loc in self._p.locations]
        counts = await camera_counts(self._s, ids)
        out = []
        for loc_id in ids:
            row = await self._s.get(Site, loc_id)
            if row is not None:
                total, online = counts.get(loc_id, (0, 0))
                out.append(
                    LocationSummary(
                        **location_out(row).model_dump(),
                        cameras_total=total,
                        cameras_online=online,
                    )
                )
        return out

    async def create(self, data: LocationIn) -> LocationOut:
        if not self._p.is_owner:
            raise Forbidden(FORBIDDEN)
        row = await self._s.get(Site, data.id)
        if row is not None and row.org_id is not None:
            raise Conflict(f"Există deja o locație cu id-ul {data.id}.")
        if row is None:  # an id the edge already reported (no org yet) is claimed instead
            row = Site(id=data.id)
            self._s.add(row)
        row.org_id = self._p.org_id
        row.name = data.name
        row.type = data.type
        row.telegram_chat_id = data.telegram_chat_id
        await self._s.flush()
        await self._audit.append(
            "location.created",
            self._p.actor,
            org_id=self._p.org_id,
            location_id=row.id,
            target=Target("location", row.id, row.name),
            after=location_json(row),
        )
        await self._s.commit()
        return location_out(row)

    async def update(self, location_id: str, patch: LocationPatch) -> LocationOut:
        self._p.authorize(LOCATIONS_MANAGE, location_id)
        row = await self._row(location_id)
        before = location_json(row)
        for key, value in patch.model_dump(exclude_unset=True).items():
            if key != "telegram_chat_id" and value is None:
                continue
            if key == "telegram_chat_id" and value != row.telegram_chat_id:
                row.telegram_chat_title = None  # the linked chat's title no longer applies
            setattr(row, key, value)
        await self._s.flush()
        await self._audit.append(
            "location.updated",
            self._p.actor,
            org_id=self._p.org_id,
            location_id=row.id,
            target=Target("location", row.id, row.name),
            before=before,
            after=location_json(row),
        )
        await self._s.commit()
        return location_out(row)

    async def delete(self, location_id: str) -> None:
        self._p.authorize(LOCATIONS_MANAGE, location_id)
        row = await self._row(location_id)
        before = location_json(row)
        await self._s.delete(row)
        await self._audit.append(
            "location.deleted",
            self._p.actor,
            org_id=self._p.org_id,
            location_id=location_id,
            target=Target("location", location_id, before["name"] or location_id),
            before=before,
        )
        await self._s.commit()


class MemberService:
    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self._s = session
        self._p = principal
        self._audit = AuditRepository(session)

    async def list(self, location_id: str) -> list[MemberOut]:
        self._p.authorize(USERS_MANAGE, location_id)
        owners = await self._s.scalars(
            select(User).where(User.org_id == self._p.org_id, User.is_owner).order_by(User.name)
        )
        out = [MemberOut(user_id=u.id, name=u.name, email=u.email, role="owner") for u in owners]
        rows = await self._s.execute(
            select(User, Membership.role)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.location_id == location_id, User.org_id == self._p.org_id)
            .order_by(User.name)
        )
        out += [
            MemberOut(user_id=u.id, name=u.name, email=u.email, role=role)  # type: ignore[arg-type]
            for u, role in rows
        ]
        push = await push_users(self._s, [m.user_id for m in out])
        return [m.model_copy(update={"push_enabled": m.user_id in push}) for m in out]

    async def _target(self, location_id: str, user_id: str) -> tuple[User, Membership | None]:
        user = await self._s.get(User, user_id)
        if user is None or user.org_id != self._p.org_id:
            raise NotFound(NO_MEMBER)
        membership = await self._s.get(Membership, (user_id, location_id))
        return user, membership

    def _check_reach(self, actor: Role, user: User, *roles: str | None) -> None:
        if user.is_owner or user.id == self._p.user_id:
            raise Forbidden(FORBIDDEN)
        for role in roles:
            if role is not None and not can_assign(actor, role):  # type: ignore[arg-type]
                raise Forbidden(FORBIDDEN)

    async def set_role(self, location_id: str, user_id: str, role: MemberRole) -> MemberOut:
        """Change a member's role; an org user without access to the location is added."""
        actor = self._p.authorize(USERS_MANAGE, location_id)
        user, membership = await self._target(location_id, user_id)
        before = membership.role if membership else None
        self._check_reach(actor, user, before, role)
        if membership is None:
            self._s.add(Membership(user_id=user_id, location_id=location_id, role=role))
        else:
            membership.role = role
        await self._s.flush()
        await self._audit.append(
            "member.role_changed",
            self._p.actor,
            org_id=self._p.org_id,
            location_id=location_id,
            target=Target("user", user.id, user.name),
            before={"role": before} if before else None,
            after={"role": role},
            from_role=before or "fără acces",
            to_role=role,
        )
        await self._s.commit()
        return MemberOut(user_id=user.id, name=user.name, email=user.email, role=role)

    async def remove(self, location_id: str, user_id: str) -> None:
        actor = self._p.authorize(USERS_MANAGE, location_id)
        user, membership = await self._target(location_id, user_id)
        if membership is None:
            raise NotFound(NO_MEMBER)
        self._check_reach(actor, user, membership.role)
        before = {"role": membership.role}
        await self._s.execute(
            delete(Membership).where(
                Membership.user_id == user_id, Membership.location_id == location_id
            )
        )
        loc = self._p.location(location_id)
        await self._audit.append(
            "member.removed",
            self._p.actor,
            org_id=self._p.org_id,
            location_id=location_id,
            target=Target("user", user.id, user.name),
            before=before,
            location=loc.name if loc else location_id,
        )
        await self._s.commit()
