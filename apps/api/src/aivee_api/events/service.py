"""Recent events and the live stream behind /ws/events (DB polling: ingest writes the rows,
so polling once a second is the simplest thing that works across processes)."""

import re
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_api.db.repositories import EventRepository, SuggestionRepository
from aivee_api.errors import NotFound
from aivee_api.events.schemas import (
    AlertMessage,
    EventOut,
    SuggestionMessage,
    event_out,
    suggestion_out,
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# The dashboard pairs raw events as opened/closed; `arrived` reaches it only through the
# folded AlertView (aivee_api.alerts), so the raw feed keeps its original two states.
LEGACY_STATES = ("opened", "closed")


async def recent_events(session: AsyncSession, limit: int) -> list[EventOut]:
    rows = await EventRepository(session).recent(limit, states=LEGACY_STATES)
    return [event_out(r) for r in rows]


def snapshot_file(snapshot_dir: Path, event_id: str) -> Path:
    """The JPEG ingest stored for `event_id` (same naming as aivee_ingest.handler)."""
    if not _SAFE_ID.match(event_id):
        raise NotFound("Imaginea nu există.")
    path = snapshot_dir / f"{event_id}.jpg"
    if not path.is_file():
        raise NotFound("Imaginea nu există.")
    return path


class LiveFeed:
    """Cursor over new events and suggestions; `poll()` returns the messages to push."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self._last_event = 0
        self._last_suggestion = 0

    async def start(self) -> None:
        async with self._sessions() as s:
            self._last_event = await EventRepository(s).max_id()
            self._last_suggestion = await SuggestionRepository(s).max_id()

    async def poll(self) -> list[BaseModel]:
        out: list[BaseModel] = []
        async with self._sessions() as s:
            for e in await EventRepository(s).after(self._last_event):
                self._last_event = e.id
                if e.state in LEGACY_STATES:
                    out.append(AlertMessage(data=event_out(e)))
            for r in await SuggestionRepository(s).after(self._last_suggestion):
                self._last_suggestion = r.id
                if r.status == "pending":
                    out.append(SuggestionMessage(data=suggestion_out(r)))
        return out
