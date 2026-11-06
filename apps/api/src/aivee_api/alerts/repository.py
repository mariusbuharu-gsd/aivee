"""Alerts over the `events` table. The opened row is the alert: it carries `alert_id`
(= its own event_id), the acknowledgement and the folded `arrived_at` / `closed_at`.
Callers own the transaction (commit)."""

import uuid
from collections.abc import Collection, Sequence
from datetime import datetime, timedelta
from typing import cast

from aivee_contracts.events import AlertEvent
from sqlalchemy import ColumnElement, Select, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from aivee_api.alerts.auth import CurrentUser
from aivee_api.alerts.domain import (
    CloseReason,
    Lifecycle,
    closed_by,
    system_close_summary_ro,
    zone_name_from_summary,
)
from aivee_api.alerts.schemas import AlertView
from aivee_api.db.models import Camera, Device, EventRow

STATE_FILTERS = ("opened", "acknowledged", "arrived", "closed", "open")


def lifecycle(row: EventRow) -> Lifecycle:
    return Lifecycle(row.at, row.acknowledged_at, row.arrived_at, row.closed_at)


def to_view(row: EventRow, location_id: str | None, zone_names: dict[str, str]) -> AlertView:
    life = lifecycle(row)
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
        acknowledged_by=row.acknowledged_by_name if row.acknowledged_at else None,
        acknowledged_by_id=row.acknowledged_by_id if row.acknowledged_at else None,
        realerted_at=row.realerted_at,
        arrived_at=row.arrived_at,
        closed_at=row.closed_at,
        closed_by=closed_by(row.closed_at, row.closed_reason),
        closed_reason=cast("CloseReason | None", row.closed_reason),
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
        alert_id, _ = await self.link_folded(event, device_id)
        return alert_id

    async def link_folded(self, event: AlertEvent, device_id: str) -> tuple[str | None, bool]:
        """`link`, and whether the event changed the alert (False for a late `closed`
        after the system already closed it, or a repeated `arrived`)."""
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
            return None, False
        await self.s.execute(
            update(EventRow).where(EventRow.event_id == event.event_id).values(alert_id=alert_id)
        )
        if event.state == "opened":
            return alert_id, True
        column = EventRow.arrived_at if event.state == "arrived" else EventRow.closed_at
        folded = await self.s.execute(
            update(EventRow)
            .where(EventRow.event_id == alert_id, column.is_(None))
            .values({column.key: event.at})
            .returning(EventRow.id)
        )
        return alert_id, folded.first() is not None

    async def claim_realerts(self, now: datetime, after_s: float) -> list[AlertView]:
        """Mark (and return) the alerts acknowledged more than `after_s` ago that nobody
        reached and that are still open: `domain.realert_due` in SQL.

        One atomic UPDATE ... WHERE realerted_at IS NULL RETURNING: a second replica
        running the same claim waits on the row lock, re-checks the WHERE after the first
        commits and gets nothing, so each alert is claimed once."""
        claimed = await self.s.execute(
            update(EventRow)
            .where(
                EventRow.state == "opened",
                EventRow.acknowledged_at < now - timedelta(seconds=after_s),
                EventRow.arrived_at.is_(None),
                EventRow.closed_at.is_(None),
                EventRow.realerted_at.is_(None),
            )
            .values(realerted_at=now)
            .returning(EventRow.event_id)
        )
        alert_ids = [alert_id for (alert_id,) in claimed.all()]
        if not alert_ids:
            return []
        return await self.views(alert_ids=alert_ids, limit=len(alert_ids))

    async def close_open_for_device(
        self, device_id: str, at: datetime, reason: CloseReason
    ) -> list[AlertView]:
        """Close every alert of the device that is still open, as the system.

        Each close also stores a `closed` event row (a deterministic id per alert and
        reason, so a second replica inserts nothing), which moves the live feed. Returns
        the alerts this call closed; callers serialise per device."""
        return await self._close_open(EventRow.device_id == device_id, at, reason)

    async def close_open_for_camera(
        self, camera_id: str, at: datetime, reason: CloseReason
    ) -> list[AlertView]:
        """`close_open_for_device` for one camera's alerts (the camera is being deleted).
        Call it before deleting the camera row, so the views still carry zone names."""
        return await self._close_open(EventRow.camera_id == camera_id, at, reason)

    async def _close_open(
        self, which: ColumnElement[bool], at: datetime, reason: CloseReason
    ) -> list[AlertView]:
        closed = await self.s.execute(
            update(EventRow)
            .where(
                which,
                EventRow.state == "opened",
                EventRow.closed_at.is_(None),
                EventRow.at <= at,
            )
            .values(closed_at=at, closed_reason=reason)
            .returning(EventRow.event_id)
        )
        alert_ids = [alert_id for (alert_id,) in closed.all()]
        if not alert_ids:
            return []
        views = await self.views(alert_ids=alert_ids, limit=len(alert_ids))
        for view in views:
            await self.s.execute(
                insert(EventRow)
                .values(
                    event_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{view.event_id}/{reason}")),
                    device_id=view.device_id,
                    rule_id=view.rule_id,
                    camera_id=view.camera_id,
                    zone_id=view.zone_id,
                    state="closed",
                    at=at,
                    summary_ro=system_close_summary_ro(view.zone_name, reason),
                    alert_id=view.event_id,
                )
                .on_conflict_do_nothing(index_elements=[EventRow.event_id])
            )
        return views

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
        return await self._stamped_after(EventRow.acknowledged_at, since)

    async def latest_realert(self) -> datetime | None:
        latest: datetime | None = await self.s.scalar(select(func.max(EventRow.realerted_at)))
        return latest

    async def realerted_after(self, since: datetime | None) -> Sequence[tuple[str, datetime]]:
        return await self._stamped_after(EventRow.realerted_at, since)

    async def _stamped_after(
        self, column: InstrumentedAttribute[datetime | None], since: datetime | None
    ) -> Sequence[tuple[str, datetime]]:
        """(alert id, stamp) of the alerts whose `column` was set after `since`, oldest first:
        the changes that store no event row (ack by the API, re-alert by ingest)."""
        stmt = select(EventRow.event_id, column).where(column.is_not(None))
        if since is not None:
            stmt = stmt.where(column > since)
        rows = (await self.s.execute(stmt.order_by(column))).all()
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
