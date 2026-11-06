"""Re-alert the whole shift when nobody arrives REALERT_AFTER_S after "Merg eu".

Every ingest replica runs the loop; `AlertRepository.claim_realerts` is one atomic
UPDATE ... WHERE realerted_at IS NULL RETURNING, so each alert is re-alerted once. The
claim and its `alert.realerted` audit entry commit together, then the notifier runs (a
failed send is logged, not retried: the dashboard still shows the alert as open).
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from aivee_api.alerts.audit import AuditWriter, realert_ro, realerted_entry
from aivee_api.alerts.repository import AlertRepository
from aivee_api.alerts.schemas import AlertView
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_ingest.notify import Notifier

log = logging.getLogger(__name__)

REALERT_TITLE = "AiVee · Nu a ajuns nimeni"


def _now() -> datetime:
    return datetime.now(UTC)


class Realerter:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        notifier: Notifier,
        audit: AuditWriter,
        after_s: float,
        now: Callable[[], datetime] = _now,
    ) -> None:
        self._sessions = sessions
        self._notifier = notifier
        self._audit = audit
        self._after_s = after_s
        self._now = now

    async def tick(self) -> list[AlertView]:
        """Claim the due alerts, audit them, then tell each one's location again."""
        now = self._now()
        async with self._sessions() as s:
            views = await AlertRepository(s).claim_realerts(now, self._after_s)
            for view in views:
                await self._audit.append(s, realerted_entry(view, now))
            await s.commit()
        for view in views:
            log.info("re-alert %s (%s): nobody arrived", view.event_id, view.zone_name)
            try:
                # The alert id as tag: Telegram finds the location's chat, Web Push its members.
                await self._notifier.send_text(
                    realert_ro(view, now), view.event_id, title=REALERT_TITLE
                )
            except Exception:
                log.exception("notifier failed for the re-alert of %s", view.event_id)
        return views


async def run_realerts(realerter: Realerter, interval_s: float) -> None:
    """Run until cancelled: one `tick` every `interval_s`; a failing tick is logged."""
    while True:
        try:
            await realerter.tick()
        except Exception:
            log.exception("re-alert check failed")
        await asyncio.sleep(interval_s)
