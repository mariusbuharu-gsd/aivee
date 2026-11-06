"""Which location an alert belongs to, and that location's Telegram chat.

Keyed by the alert's event id (stored before any notifier runs): the producing device's
location, else its camera's. The notifiers keep the plain Notifier port this way.
"""

from aivee_api.auth.scope import event_location
from aivee_api.db.models import Site
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def alert_location(sessions: async_sessionmaker[AsyncSession], event_id: str) -> str | None:
    async with sessions() as s:
        return await event_location(s, event_id)


async def telegram_chat_for(
    sessions: async_sessionmaker[AsyncSession], event_id: str
) -> str | None:
    """The location's own `telegram_chat_id`, or None (callers fall back to TELEGRAM_CHAT_ID)."""
    async with sessions() as s:
        location_id = await event_location(s, event_id)
        if location_id is None:
            return None
        site = await s.get(Site, location_id)
        return site.telegram_chat_id if site and site.telegram_chat_id else None
