"""Send one Web Push message to every stored subscription; drop the ones that are gone."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_api.push.repository import PushSubscriptionRepository
from aivee_api.push.sender import GONE, PushMessage, PushReport, PushSender, Subscription

log = logging.getLogger(__name__)


async def push_to_all(
    sessions: async_sessionmaker[AsyncSession], sender: PushSender, message: PushMessage
) -> PushReport:
    async with sessions() as s:
        subs = await PushSubscriptionRepository(s).all()
    if not subs:
        return PushReport()
    payload = message.payload()

    async def one(sub: Subscription) -> int:
        try:
            return await sender.send(sub, payload)
        except Exception:
            log.exception("push to %s failed", sub.endpoint[:60])
            return 0

    statuses = await asyncio.gather(*(one(sub) for sub in subs))
    gone = [sub.endpoint for sub, st in zip(subs, statuses, strict=True) if st in GONE]
    if gone:
        async with sessions() as s:
            await PushSubscriptionRepository(s).delete_many(gone)
            await s.commit()
    sent = sum(1 for st in statuses if 200 <= st < 300)
    report = PushReport(sent=sent, removed=len(gone), failed=len(subs) - sent - len(gone))
    log.info("push %r: %s", message.tag, report)
    return report
