"""GET /api/audit: the history, newest first, cursor-paginated (`before` = an entry id).

Scope (audit.view / audit.view.own): owner → the whole organization; manager → their
locations; staff → their own actions. Everyone also sees their own actions.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

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
    rows = await AuditRepository(s).query(
        visibility(p),
        location_id=location_id,
        actor_id=actor,
        kind=kind,
        before=cursor,
        since=since,
        until=until,
        limit=limit,
    )
    items = [entry_out(r) for r in rows]
    return AuditPage(items=items, next_before=items[-1].id if len(items) == limit else None)
