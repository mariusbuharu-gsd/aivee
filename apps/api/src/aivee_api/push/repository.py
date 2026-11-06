"""Push subscriptions over an AsyncSession. Callers own the transaction (commit)."""

from collections.abc import Iterable, Sequence

from sqlalchemy import delete, exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.accounts.models import Membership, User
from aivee_api.db.models import PushSubscriptionRow, Site
from aivee_api.push.sender import Subscription


class PushSubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def upsert(
        self, sub: Subscription, user_agent: str = "", user_id: str | None = None
    ) -> None:
        """A browser re-subscribing with the same endpoint may rotate its keys; the endpoint
        follows whoever is logged in on that browser now."""
        values = {
            "p256dh": sub.p256dh,
            "auth": sub.auth,
            "user_agent": user_agent[:300],
            "user_id": user_id,
        }
        stmt = insert(PushSubscriptionRow).values(endpoint=sub.endpoint, **values)
        await self.s.execute(
            stmt.on_conflict_do_update(index_elements=[PushSubscriptionRow.endpoint], set_=values)
        )

    async def delete(self, endpoint: str, user_id: str | None = None) -> bool:
        """With `user_id`, only that user's subscription is removed."""
        stmt = delete(PushSubscriptionRow).where(PushSubscriptionRow.endpoint == endpoint)
        if user_id is not None:
            stmt = stmt.where(PushSubscriptionRow.user_id == user_id)
        result = await self.s.execute(stmt.returning(PushSubscriptionRow.id))
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

    async def for_user(self, user_id: str) -> Sequence[Subscription]:
        rows = await self.s.scalars(
            select(PushSubscriptionRow)
            .where(PushSubscriptionRow.user_id == user_id)
            .order_by(PushSubscriptionRow.id)
        )
        return [Subscription(r.endpoint, r.p256dh, r.auth) for r in rows]

    async def for_location(self, location_id: str) -> Sequence[Subscription]:
        """Subscriptions of everyone who sees the location's alerts: its members and the
        owners of its organization. Subscriptions without a user get nothing."""
        member = exists().where(
            Membership.user_id == User.id, Membership.location_id == location_id
        )
        owner_org = select(Site.org_id).where(Site.id == location_id).scalar_subquery()
        rows = await self.s.scalars(
            select(PushSubscriptionRow)
            .join(User, User.id == PushSubscriptionRow.user_id)
            .where(or_(member, User.is_owner & (User.org_id == owner_org)))
            .order_by(PushSubscriptionRow.id)
        )
        return [Subscription(r.endpoint, r.p256dh, r.auth) for r in rows]
