"""Locations of an organization and their members (users.manage, locations.manage)."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.accounts.models import Membership, User
from aivee_api.audit.repository import AuditRepository, Target
from aivee_api.auth.permissions import (
    LOCATIONS_MANAGE,
    RULES_MANAGE,
    USERS_MANAGE,
    MemberRole,
    Role,
    can_assign,
)
from aivee_api.auth.principal import FORBIDDEN, NO_LOCATION, Principal
from aivee_api.db.models import Site
from aivee_api.errors import Conflict, Forbidden, NotFound
from aivee_api.locations.schemas import (
    LocationIn,
    LocationOut,
    LocationPatch,
    MemberOut,
    location_json,
    location_out,
)

NO_MEMBER = "Utilizatorul nu există."
TARGET_FIELDS = frozenset({"service_target_s"})
NULLABLE_FIELDS = frozenset({"telegram_chat_id", "service_target_s"})


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

    async def visible(self) -> list[LocationOut]:
        out = []
        for loc in self._p.locations:
            row = await self._s.get(Site, loc.id)
            if row is not None:
                out.append(location_out(row))
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
        changes = patch.model_dump(exclude_unset=True)
        # The service target is the team's goal, not the location's identity: managers set it
        # too (rules.manage). Anything else stays owner-only (locations.manage).
        target_only = bool(changes) and changes.keys() <= TARGET_FIELDS
        self._p.authorize(RULES_MANAGE if target_only else LOCATIONS_MANAGE, location_id)
        row = await self._row(location_id)
        before = location_json(row)
        for key, value in changes.items():
            if key not in NULLABLE_FIELDS and value is None:
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
        return out

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
