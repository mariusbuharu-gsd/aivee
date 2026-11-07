"""Where each Telegram alert went (chat + message id), kept on the alert's opened row so any
ingest replica can edit it or reply to it later."""

from dataclasses import dataclass
from typing import Protocol

from aivee_api.db.models import EventRow
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True)
class SentMessage:
    chat_id: str
    message_id: int
    photo: bool


class SentMessages(Protocol):
    async def save(self, alert_id: str, sent: SentMessage) -> None: ...

    async def get(self, alert_id: str) -> SentMessage | None: ...


class DbSentMessages:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def save(self, alert_id: str, sent: SentMessage) -> None:
        async with self._sessions() as s:
            await s.execute(
                update(EventRow)
                .where(EventRow.event_id == alert_id)
                .values(
                    telegram_chat_id=sent.chat_id,
                    telegram_message_id=sent.message_id,
                    telegram_photo=sent.photo,
                )
            )
            await s.commit()

    async def get(self, alert_id: str) -> SentMessage | None:
        async with self._sessions() as s:
            row = (
                await s.execute(
                    select(
                        EventRow.telegram_chat_id,
                        EventRow.telegram_message_id,
                        EventRow.telegram_photo,
                    ).where(EventRow.event_id == alert_id)
                )
            ).first()
        if row is None or not row[0] or row[1] is None:
            return None
        return SentMessage(str(row[0]), int(row[1]), bool(row[2]))


class MemorySentMessages:
    """For tests and runs without a database."""

    def __init__(self) -> None:
        self.items: dict[str, SentMessage] = {}

    async def save(self, alert_id: str, sent: SentMessage) -> None:
        self.items[alert_id] = sent

    async def get(self, alert_id: str) -> SentMessage | None:
        return self.items.get(alert_id)
