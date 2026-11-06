"""Folded alert updates for /ws/events: one AlertView message per alert that changed
(a new event row for it, an acknowledgement, a re-alert or a verification) since the last poll."""

from collections.abc import Collection
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_api.alerts.repository import AlertRepository
from aivee_api.alerts.schemas import AlertViewMessage
from aivee_api.db.repositories import EventRepository


class AlertFeed:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        location_ids: Collection[str] | None = None,
    ) -> None:
        self._sessions = sessions
        self._locations = location_ids
        self._last_row = 0
        self._last_ack: datetime | None = None
        self._last_realert: datetime | None = None
        self._last_verified: datetime | None = None

    async def start(self) -> None:
        async with self._sessions() as s:
            self._last_row = await EventRepository(s).max_id()
            repo = AlertRepository(s)
            self._last_ack = await repo.latest_ack()
            self._last_realert = await repo.latest_realert()
            self._last_verified = await repo.latest_verification()

    async def poll(self) -> list[AlertViewMessage]:
        async with self._sessions() as s:
            repo = AlertRepository(s)
            self._last_row, changed = await repo.alert_ids_after(self._last_row)
            acked = await repo.acknowledged_after(self._last_ack)
            if acked:
                self._last_ack = acked[-1][1]
            realerted = await repo.realerted_after(self._last_realert)
            if realerted:
                self._last_realert = realerted[-1][1]
            verified = await repo.verified_after(self._last_verified)
            if verified:
                self._last_verified = verified[-1][1]
            stamped = (a for a, _ in [*acked, *realerted, *verified])
            ids = list(dict.fromkeys([*changed, *stamped]))
            if not ids:
                return []
            views = await repo.views(alert_ids=ids, location_ids=self._locations, limit=len(ids))
        views.sort(key=lambda v: v.at)
        return [AlertViewMessage(data=v) for v in views]
