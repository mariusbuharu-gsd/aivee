"""Push subscriptions over an AsyncSession. Callers own the transaction (commit)."""

from collections.abc import Iterable, Sequence

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.db.models import PushSubscriptionRow
from aivee_api.push.sender import Subscription


class PushSubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def upsert(self, sub: Subscription, user_agent: str = "") -> None:
        """A browser re-subscribing with the same endpoint may rotate its keys."""
        values = {"p256dh": sub.p256dh, "auth": sub.auth, "user_agent": user_agent[:300]}
        stmt = insert(PushSubscriptionRow).values(endpoint=sub.endpoint, **values)
        await self.s.execute(
            stmt.on_conflict_do_update(index_elements=[PushSubscriptionRow.endpoint], set_=values)
        )

    async def delete(self, endpoint: str) -> bool:
        result = await self.s.execute(
            delete(PushSubscriptionRow)
            .where(PushSubscriptionRow.endpoint == endpoint)
            .returning(PushSubscriptionRow.id)
        )
        return result.first() is not None

    async def delete_many(self, endpoints: Iterable[str]) -> None:
        endpoints = list(endpoints)
        if endpoints:
            await self.s.execute(
                delete(PushSubscriptionRow).where(PushSubscriptionRow.endpoint.in_(endpoints))
            )

    async def all(self) -> Sequence[Subscription]:
        rows = await self.s.scalars(select(PushSubscriptionRow).order_by(PushSubscriptionRow.id))
        return [Subscription(r.endpoint, r.p256dh, r.auth) for r in rows]
