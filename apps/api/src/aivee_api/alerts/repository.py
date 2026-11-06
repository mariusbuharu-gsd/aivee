"""Alerts over the `events` table. The opened row is the alert: it carries `alert_id`
(= its own event_id), the acknowledgement and the folded `arrived_at` / `closed_at`.
Callers own the transaction (commit)."""

from collections.abc import Collection, Sequence
from datetime import datetime

from aivee_contracts.events import AlertEvent
from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.alerts.auth import CurrentUser
from aivee_api.alerts.domain import Lifecycle, zone_name_from_summary
from aivee_api.alerts.schemas import AckBy, AlertView
from aivee_api.db.models import Camera, Device, EventRow

STATE_FILTERS = ("opened", "acknowledged", "arrived", "closed", "open")


def lifecycle(row: EventRow) -> Lifecycle:
    return Lifecycle(row.at, row.acknowledged_at, row.arrived_at, row.closed_at)


def to_view(row: EventRow, location_id: str | None, zone_names: dict[str, str]) -> AlertView:
    life = lifecycle(row)
    ack = (
        AckBy(id=row.acknowledged_by_id or "", name=row.acknowledged_by_name or "")
        if row.acknowledged_at is not None
        else None
    )
    zone_name = zone_names.get(row.zone_id) or zone_name_from_summary(row.summary_ro) or row.zone_id
    return AlertView(
        event_id=row.event_id,
        rule_id=row.rule_id,
        location_id=location_id,
        camera_id=row.camera_id,
        zone_id=row.zone_id,
        zone_name=zone_name,
        summary_ro=row.summary_ro,
        opened_at=row.at,
        acknowledged_at=row.acknowledged_at,
        acknowledged_by=ack,
        arrived_at=row.arrived_at,
        closed_at=row.closed_at,
        wait_s=life.wait_s,
        reaction_s=life.reaction_s,
        travel_s=life.travel_s,
        unacknowledged_arrival=life.unacknowledged_arrival,
        state=life.state,
        at=life.last_change,
        device_id=row.device_id,
        snapshot=row.snapshot_path is not None,
        snapshot_url=f"/api/snapshots/{row.event_id}" if row.snapshot_path else None,
    )


AlertQuery = Select[EventRow, str]


def _state_filter(stmt: AlertQuery, state: str) -> AlertQuery:
    match state:
        case "open":
            return stmt.where(EventRow.closed_at.is_(None))
        case "closed":
            return stmt.where(EventRow.closed_at.is_not(None))
        case "arrived":
            return stmt.where(EventRow.arrived_at.is_not(None), EventRow.closed_at.is_(None))
        case "acknowledged":
            return stmt.where(
                EventRow.acknowledged_at.is_not(None),
                EventRow.arrived_at.is_(None),
                EventRow.closed_at.is_(None),
            )
        case _:  # opened: nothing happened yet
            return stmt.where(
                EventRow.acknowledged_at.is_(None),
                EventRow.arrived_at.is_(None),
                EventRow.closed_at.is_(None),
            )


class AlertRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    # -- ingest ------------------------------------------------------------------------

    async def link(self, event: AlertEvent, device_id: str) -> str | None:
        """After storing `event`: point its row at the alert and fold its time into the
        opened row. Returns the alert id (the opened event's id), None if unknown."""
        if event.state == "opened":
            alert_id: str | None = event.event_id
        else:
            alert_id = await self.s.scalar(
                select(EventRow.event_id)
                .where(
                    EventRow.state == "opened",
                    EventRow.device_id == device_id,
                    EventRow.camera_id == event.camera_id,
                    EventRow.rule_id == event.rule_id,
                    EventRow.zone_id == event.zone_id,
                    EventRow.at <= event.at,
                )
                .order_by(EventRow.at.desc())
                .limit(1)
            )
        if alert_id is None:
            return None
        await self.s.execute(
            update(EventRow).where(EventRow.event_id == event.event_id).values(alert_id=alert_id)
        )
        if event.state != "opened":
            column = EventRow.arrived_at if event.state == "arrived" else EventRow.closed_at
            await self.s.execute(
                update(EventRow)
                .where(EventRow.event_id == alert_id, column.is_(None))
                .values({column.key: event.at})
            )
        return alert_id

    # -- api ---------------------------------------------------------------------------

    async def acknowledge(self, alert_id: str, user: CurrentUser, at: datetime) -> bool:
        """Atomically acknowledge an open, not yet acknowledged alert."""
        result = await self.s.execute(
            update(EventRow)
            .where(
                EventRow.event_id == alert_id,
                EventRow.state == "opened",
                EventRow.acknowledged_at.is_(None),
                EventRow.closed_at.is_(None),
            )
            .values(acknowledged_at=at, acknowledged_by_id=user.id, acknowledged_by_name=user.name)
            .returning(EventRow.id)
        )
        return result.first() is not None

    async def resolve(self, event_id: str) -> str | None:
        """The alert id for any of its events' ids."""
        row = await self.s.scalar(select(EventRow).where(EventRow.event_id == event_id))
        if row is None:
            return None
        return row.event_id if row.state == "opened" else row.alert_id

    async def view(self, alert_id: str) -> AlertView | None:
        views = await self.views(alert_ids=[alert_id], limit=1)
        return views[0] if views else None

    async def views(
        self,
        *,
        alert_ids: Collection[str] | None = None,
        location_ids: Collection[str] | None = None,
        state: str | None = None,
        opened_from: datetime | None = None,
        opened_to: datetime | None = None,
        limit: int = 50,
    ) -> list[AlertView]:
        """Folded alerts, newest first."""
        stmt = (
            select(EventRow, Device.site_id)
            .outerjoin(Device, Device.id == EventRow.device_id)
            .where(EventRow.state == "opened")
            .order_by(EventRow.at.desc())
            .limit(limit)
        )
        if alert_ids is not None:
            stmt = stmt.where(EventRow.event_id.in_(alert_ids))
        if location_ids is not None:
            stmt = stmt.where(Device.site_id.in_(location_ids))
        if state is not None:
            stmt = _state_filter(stmt, state)
        if opened_from is not None:
            stmt = stmt.where(EventRow.at >= opened_from)
        if opened_to is not None:
            stmt = stmt.where(EventRow.at < opened_to)
        rows = (await self.s.execute(stmt)).all()
        names = await self._zone_names({r[0].camera_id for r in rows})
        return [to_view(row, site, names.get(row.camera_id, {})) for row, site in rows]

    async def _zone_names(self, camera_ids: Collection[str]) -> dict[str, dict[str, str]]:
        if not camera_ids:
            return {}
        cameras = await self.s.scalars(select(Camera).where(Camera.id.in_(camera_ids)))
        return {
            c.id: {str(z.get("id")): str(z.get("name", "")) for z in c.zones or []} for c in cameras
        }

    # -- live --------------------------------------------------------------------------

    async def latest_ack(self) -> datetime | None:
        latest: datetime | None = await self.s.scalar(select(func.max(EventRow.acknowledged_at)))
        return latest

    async def acknowledged_after(self, since: datetime | None) -> Sequence[tuple[str, datetime]]:
        stmt = select(EventRow.event_id, EventRow.acknowledged_at).where(
            EventRow.acknowledged_at.is_not(None)
        )
        if since is not None:
            stmt = stmt.where(EventRow.acknowledged_at > since)
        rows = (await self.s.execute(stmt.order_by(EventRow.acknowledged_at))).all()
        return [(event_id, at) for event_id, at in rows if at is not None]

    async def alert_ids_after(self, last_row_id: int, limit: int = 100) -> tuple[int, list[str]]:
        """Alert ids touched by event rows stored after `last_row_id`, and the new cursor."""
        rows = (
            await self.s.execute(
                select(EventRow.id, EventRow.alert_id)
                .where(EventRow.id > last_row_id)
                .order_by(EventRow.id)
                .limit(limit)
            )
        ).all()
        cursor = rows[-1][0] if rows else last_row_id
        return cursor, list(dict.fromkeys(a for _, a in rows if a is not None))
