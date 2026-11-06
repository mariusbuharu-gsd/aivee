"""GET /api/audit: the history, newest first, cursor-paginated (`before` = an entry id).

Scope (audit.view / audit.view.own): owner → the whole organization; manager → their
locations; staff → their own actions. Everyone also sees their own actions.

Entries without a location (auth.login, auth.logout, auth.login_failed) still show under a
`location_id` filter: for an owner every one of the org, for a manager those whose actor
is a member of that location, for staff their own.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.accounts.models import Membership
from aivee_api.audit.models import AuditRow
from aivee_api.audit.repository import AuditRepository, Visibility
from aivee_api.auth.deps import CurrentUser
from aivee_api.auth.permissions import AUDIT_VIEW
from aivee_api.auth.principal import NO_LOCATION, Principal
from aivee_api.deps import SessionDep
from aivee_api.errors import Invalid, NotFound

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditActor(BaseModel):
    kind: Literal["user", "device", "system"]
    id: str
    name: str


class AuditTarget(BaseModel):
    type: str
    id: str
    label: str


class AuditEntry(BaseModel):
    id: str
    at: datetime
    location_id: str | None
    actor: AuditActor
    kind: str
    target: AuditTarget | None
    summary_ro: str
    before: Any | None
    after: Any | None


class AuditPage(BaseModel):
    items: list[AuditEntry]
    next_before: str | None


def entry_out(row: AuditRow) -> AuditEntry:
    target = None
    if row.target_type is not None:
        target = AuditTarget(
            type=row.target_type, id=row.target_id or "", label=row.target_label or ""
        )
    return AuditEntry(
        id=str(row.id),
        at=row.at,
        location_id=row.location_id,
        actor=AuditActor(kind=row.actor_kind, id=row.actor_id, name=row.actor_name),  # type: ignore[arg-type]
        kind=row.kind,
        target=target,
        summary_ro=row.summary_ro,
        before=row.before,
        after=row.after,
    )


def visibility(p: Principal) -> Visibility:
    if p.is_owner:
        return Visibility(p.org_id, all_rows=True)
    return Visibility(p.org_id, location_ids=p.locations_with(AUDIT_VIEW), actor_id=p.user_id)


@dataclass(frozen=True)
class LocationScope:
    visibility: Visibility
    unlocated_actor_ids: Collection[str] | None  # None: every location-less entry visible


async def location_scope(s: AsyncSession, p: Principal, location_id: str) -> LocationScope:
    """What a reader sees under `location_id` (a location they belong to)."""
    if p.is_owner:
        return LocationScope(Visibility(p.org_id, all_rows=True), None)
    if p.can(AUDIT_VIEW, location_id):
        # The whole location is theirs; location-less entries only of its members.
        members = await s.scalars(
            select(Membership.user_id).where(Membership.location_id == location_id)
        )
        return LocationScope(Visibility(p.org_id, all_rows=True), set(members.all()))
    # audit.view.own: their own actions there and their own location-less ones.
    return LocationScope(Visibility(p.org_id, actor_id=p.user_id), None)


@router.get("")
async def list_audit(
    s: SessionDep,
    p: CurrentUser,
    location_id: Annotated[str | None, Query(max_length=64)] = None,
    actor: Annotated[str | None, Query(max_length=64)] = None,
    kind: Annotated[str | None, Query(max_length=64)] = None,
    before: Annotated[str | None, Query(max_length=20)] = None,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditPage:
    if location_id is not None and p.role_at(location_id) is None:
        raise NotFound(NO_LOCATION)
    cursor: int | None = None
    if before:
        if not before.isdigit():
            raise Invalid("Cursorul `before` nu este valid.")
        cursor = int(before)
    scope = visibility(p)
    unlocated_actors: Collection[str] | None = None
    if location_id is not None:
        where = await location_scope(s, p, location_id)
        scope, unlocated_actors = where.visibility, where.unlocated_actor_ids
    rows = await AuditRepository(s).query(
        scope,
        location_id=location_id,
        with_unlocated=location_id is not None,
        unlocated_actor_ids=unlocated_actors,
        actor_id=actor,
        kind=kind,
        before=cursor,
        since=since,
        until=until,
        limit=limit,
    )
    items = [entry_out(r) for r in rows]
    return AuditPage(items=items, next_before=items[-1].id if len(items) == limit else None)
