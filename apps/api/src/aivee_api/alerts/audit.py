"""Audit port for `alert.*` entries.

`RepositoryAuditWriter` appends to audit_log in the caller's session, so the entry commits
with the change (the API's ack, ingest's event). `LoggingAuditWriter` only logs (tests).
"""

import logging
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.alerts.auth import CurrentUser
from aivee_api.alerts.domain import duration_ro, system_close_summary_ro
from aivee_api.alerts.schemas import AlertView
from aivee_api.audit.repository import Actor, AuditRepository, Target
from aivee_api.db.models import Site

log = logging.getLogger(__name__)

ActorKind = Literal["user", "device", "system"]


@dataclass(frozen=True)
class AlertAuditEntry:
    """Mirrors the spec's AuditEntry, minus the id and time the table assigns."""

    kind: str  # alert.opened | .acknowledged | .realerted | .arrived | .closed
    location_id: str | None
    actor_kind: ActorKind
    actor_id: str
    actor_name: str
    target_type: str
    target_id: str
    target_label: str
    summary_ro: str
    before: Any = None
    after: Any = None


class AuditWriter(Protocol):
    async def append(self, session: AsyncSession, entry: AlertAuditEntry) -> None: ...


class LoggingAuditWriter:
    async def append(self, session: AsyncSession, entry: AlertAuditEntry) -> None:
        log.info(
            "audit kind=%s location=%s actor=%s:%s target=%s:%s summary=%r",
            entry.kind,
            entry.location_id,
            entry.actor_kind,
            entry.actor_id,
            entry.target_type,
            entry.target_id,
            entry.summary_ro,
        )


class RepositoryAuditWriter:
    """Writes the entry to audit_log; the organization is the location's."""

    async def append(self, session: AsyncSession, entry: AlertAuditEntry) -> None:
        site = await session.get(Site, entry.location_id) if entry.location_id else None
        await AuditRepository(session).append(
            entry.kind,
            Actor(entry.actor_kind, entry.actor_id, entry.actor_name),
            org_id=site.org_id if site else None,
            location_id=entry.location_id,
            target=Target(entry.target_type, entry.target_id, entry.target_label),
            before=entry.before,
            after=entry.after,
            summary=entry.summary_ro,
        )


_DEFAULT = RepositoryAuditWriter()


def get_audit_writer() -> AuditWriter:
    """FastAPI dependency (tests override it)."""
    return _DEFAULT


def arrival_ro(view: AlertView) -> str:
    """ "Ana a ajuns la Masa 4 după 2 min 10 s" (the acknowledger, else "Un angajat")."""
    who = view.acknowledged_by or "Un angajat"
    after = f" după {duration_ro(view.wait_s)}" if view.wait_s is not None else ""
    return f"{who} a ajuns la {view.zone_name}{after}"


def realert_ro(view: AlertView, now: datetime) -> str:
    """ "Masa 4: Ana a confirmat acum 2 min, încă nu a ajuns nimeni" (whole minutes)."""
    who = view.acknowledged_by or "Cineva"
    since = (now - view.acknowledged_at).total_seconds() if view.acknowledged_at else 0
    minutes = max(1, int(since // 60))
    return f"{view.zone_name}: {who} a confirmat acum {minutes} min, încă nu a ajuns nimeni"


def _entry(
    view: AlertView, kind: str, actor: tuple[ActorKind, str, str], summary: str
) -> AlertAuditEntry:
    return AlertAuditEntry(
        kind=kind,
        location_id=view.location_id,
        actor_kind=actor[0],
        actor_id=actor[1],
        actor_name=actor[2],
        target_type="alert",
        target_id=view.event_id,
        target_label=view.zone_name,
        summary_ro=summary,
    )


def acknowledged_entry(view: AlertView, user: CurrentUser) -> AlertAuditEntry:
    return _entry(
        view,
        "alert.acknowledged",
        ("user", user.id, user.name),
        f"{user.name} a preluat alerta de la {view.zone_name}",
    )


def system_closed_entry(view: AlertView, reason: str) -> AlertAuditEntry:
    """Ingest closed the alert because its device went away (actor = the system)."""
    entry = _entry(
        view,
        "alert.closed",
        ("system", "system", "AiVee"),
        system_close_summary_ro(view.zone_name, reason),
    )
    return replace(entry, after={"reason": reason})


def realerted_entry(view: AlertView, now: datetime) -> AlertAuditEntry:
    """Ingest told the whole shift again: acknowledged, nobody arrived (actor = the system)."""
    entry = _entry(view, "alert.realerted", ("system", "system", "AiVee"), realert_ro(view, now))
    return replace(entry, after={"realerted_at": now.isoformat()})


def device_entry(view: AlertView, state: str) -> AlertAuditEntry | None:
    """The entry ingest writes for an edge event (actor = the device)."""
    actor: tuple[ActorKind, str, str] = ("device", view.device_id, view.device_id)
    zone = view.zone_name
    match state:
        case "opened":
            summary = f"Alertă nouă: {view.summary_ro}"
        case "arrived":
            summary = arrival_ro(view)
            if view.unacknowledged_arrival:
                summary += " (fără preluare)"
        case "closed":
            summary = f"Alerta de la {zone} s-a închis"
        case _:
            return None
    return _entry(view, f"alert.{state}", actor, summary)
