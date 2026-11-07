"""Remind the location every REMIND_S while an alert is open and nobody arrived.

    ⏰ Încă neservit: Masa 1, de 4 min      (Telegram: a reply to the alert, same buttons)

Every ingest replica may run the loop: the claim is one atomic UPDATE ... RETURNING on
`events.reminded_at` (the pattern of `claim_realerts`), so a reminder goes out once per
alert per period whichever replica wins, and a restart picks up from the database instead
of starting over. The first reminder comes REMIND_S after the alert opened. "Preiau" does
not stop them; arrival and close do.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from aivee_api.alerts.repository import AlertRepository
from aivee_api.alerts.schemas import AlertView
from aivee_api.db.models import EventRow
from aivee_api.videos.kind import not_upload
from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_ingest.lifecycle import is_guest_rule, reminder_ro
from aivee_ingest.locations import rule_conditions
from aivee_ingest.notify import LifecycleNotifier, Notifier

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


async def claim_reminders(s: AsyncSession, now: datetime, every_s: float) -> list[AlertView]:
    """Mark (and return) the open, unreached alerts due for a reminder."""
    due = now - timedelta(seconds=every_s)
    claimed = await s.execute(
        update(EventRow)
        .where(
            EventRow.state == "opened",
            EventRow.at <= due,
            EventRow.arrived_at.is_(None),
            EventRow.closed_at.is_(None),
            or_(EventRow.reminded_at.is_(None), EventRow.reminded_at <= due),
            not_upload(EventRow.device_id, EventRow.camera_id),  # a clip never reminds
        )
        .values(reminded_at=now)
        .returning(EventRow.event_id)
    )
    alert_ids = [alert_id for (alert_id,) in claimed.all()]
    if not alert_ids:
        return []
    return await AlertRepository(s).views(alert_ids=alert_ids, limit=len(alert_ids))


class Reminder:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        notifier: Notifier,
        every_s: float,
        now: Callable[[], datetime] = _now,
    ) -> None:
        self._sessions = sessions
        self._notifier = notifier
        self._every_s = every_s
        self._now = now

    async def tick(self) -> list[AlertView]:
        now = self._now()
        async with self._sessions() as s:
            views = await claim_reminders(s, now, self._every_s)
            await s.commit()
        for view in views:
            guest = is_guest_rule(await rule_conditions(self._sessions, view.rule_id))
            text = reminder_ro(view, now, guest=guest)
            log.info("reminder %s: %s", view.event_id, text)
            try:
                if isinstance(self._notifier, LifecycleNotifier):
                    await self._notifier.alert_reminder(view, text)
                else:
                    await self._notifier.send_text(text, view.event_id, kind="realert")
            except Exception:
                log.exception("notifier failed for the reminder of %s", view.event_id)
        return views


async def run_reminders(reminder: Reminder, interval_s: float) -> None:
    """Run until cancelled: one `tick` every `interval_s`; a failing tick is logged."""
    while True:
        try:
            await reminder.tick()
        except Exception:
            log.exception("reminder check failed")
        await asyncio.sleep(interval_s)
