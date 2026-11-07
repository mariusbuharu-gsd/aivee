"""The only door to audit_log: `append` and `query` (no update, no delete, by design).

Callers own the transaction: append inside the same unit of work as the change it records.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import ColumnElement, and_, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.audit.models import AuditRow
from aivee_api.audit.summaries import summary_ro

ActorKind = Literal["user", "device", "system"]


@dataclass(frozen=True)
class Actor:
    kind: ActorKind
    id: str
    name: str


@dataclass(frozen=True)
class Target:
    type: str
    id: str
    label: str


@dataclass(frozen=True)
class Visibility:
    """Which rows a reader may see within their organization: every row (`all_rows`), rows
    of `location_ids`, and always the reader's own actions (`actor_id`)."""

    org_id: str
    all_rows: bool = False
    location_ids: Collection[str] = ()
    actor_id: str | None = None


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def append(
        self,
        kind: str,
        actor: Actor,
        *,
        org_id: str | None,
        location_id: str | None = None,
        target: Target | None = None,
        before: Any = None,
        after: Any = None,
        summary: str | None = None,
        **fields: str,
    ) -> AuditRow:
        """`summary` overrides the kind's template (callers that already phrased it)."""
        row = AuditRow(
            org_id=org_id,
            location_id=location_id,
            actor_kind=actor.kind,
            actor_id=actor.id,
            actor_name=actor.name,
            kind=kind,
            target_type=target.type if target else None,
            target_id=target.id if target else None,
            target_label=target.label if target else None,
            summary_ro=summary
            or summary_ro(kind, actor=actor.name, target=target.label if target else "", **fields),
            before=before,
            after=after,
        )
        self.s.add(row)
        await self.s.flush()
        return row

    async def query(
        self,
        visibility: Visibility,
        *,
        location_id: str | None = None,
        with_unlocated: bool = False,
        unlocated_actor_ids: Collection[str] | None = None,
        actor_id: str | None = None,
        kind: str | None = None,
        before: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
    ) -> Sequence[AuditRow]:
        """Newest first. `kind` without a dot ("rule") matches the whole family ("rule.*").

        With `location_id` and `with_unlocated`, entries without a location (auth.*) come
        along: all of them, or only those whose actor is in `unlocated_actor_ids`."""
        stmt = select(AuditRow).where(AuditRow.org_id == visibility.org_id)
        if not visibility.all_rows:
            scope: list[ColumnElement[bool]] = []
            if visibility.location_ids:
                scope.append(AuditRow.location_id.in_(list(visibility.location_ids)))
            if visibility.actor_id:
                scope.append(AuditRow.actor_id == visibility.actor_id)
            stmt = stmt.where(or_(*scope) if scope else false())
        if location_id is not None:
            here: ColumnElement[bool] = AuditRow.location_id == location_id
            if with_unlocated:
                unlocated: ColumnElement[bool] = AuditRow.location_id.is_(None)
                if unlocated_actor_ids is not None:
                    unlocated = and_(unlocated, AuditRow.actor_id.in_(list(unlocated_actor_ids)))
                here = or_(here, unlocated)
            stmt = stmt.where(here)
        if actor_id is not None:
            stmt = stmt.where(AuditRow.actor_id == actor_id)
        if kind:
            family = kind.removesuffix(".*")
            if "." in kind and not kind.endswith(".*"):
                stmt = stmt.where(AuditRow.kind == kind)
            else:
                stmt = stmt.where(AuditRow.kind.startswith(f"{family}.", autoescape=True))
        if before is not None:
            stmt = stmt.where(AuditRow.id < before)
        if since is not None:
            stmt = stmt.where(AuditRow.at >= since)
        if until is not None:
            stmt = stmt.where(AuditRow.at < until)
        stmt = stmt.order_by(AuditRow.id.desc()).limit(limit)
        return (await self.s.scalars(stmt)).all()
