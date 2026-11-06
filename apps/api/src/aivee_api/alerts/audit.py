"""Audit port for `alert.*` entries. The audit_log table comes from the auth stream (A).

Until then `LoggingAuditWriter` logs each entry. At merge, implement `AuditWriter` over
stream A's audit repository (`append` in the caller's session, so the entry commits with
the change) and return it from `get_audit_writer` (API) / pass it to `IngestHandler`.
"""

import logging
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.alerts.auth import CurrentUser
from aivee_api.alerts.domain import duration_ro
from aivee_api.alerts.schemas import AlertView

log = logging.getLogger(__name__)

ActorKind = Literal["user", "device", "system"]


@dataclass(frozen=True)
class AlertAuditEntry:
    """Mirrors the spec's AuditEntry, minus the id and time the table assigns."""

    kind: str  # alert.opened | alert.acknowledged | alert.arrived | alert.closed
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


_DEFAULT = LoggingAuditWriter()


def get_audit_writer() -> AuditWriter:
    """FastAPI dependency; override (or change) at merge to write the real audit_log."""
    return _DEFAULT


def arrival_ro(view: AlertView) -> str:
    """ "Ana a ajuns la Masa 4 după 2 min 10 s" (the acknowledger, else "Un angajat")."""
    who = view.acknowledged_by.name if view.acknowledged_by else "Un angajat"
    after = f" după {duration_ro(view.wait_s)}" if view.wait_s is not None else ""
    return f"{who} a ajuns la {view.zone_name}{after}"


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
