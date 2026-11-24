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
from aivee_api.videos.kind import is_upload

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# The dashboard pairs raw events as opened/closed; `arrived` reaches it only through the
# folded AlertView (aivee_api.alerts), so the raw feed keeps its original two states.
LEGACY_STATES = ("opened", "closed")


async def recent_events(session: AsyncSession, limit: int) -> list[EventOut]:
    rows = await EventRepository(session).recent(limit, states=LEGACY_STATES)
    return [event_out(r) for r in rows]


def snapshot_key(site: str, device: str, snapshot_id: str) -> str | None:
    """Where ingest stores the JPEG sent on `aivee/<site>/<device>/snapshots/<id>`, relative
    to SNAPSHOT_DIR: `<site>/<device>/<id>.jpg`. Keyed by the topic (the broker ACL pins the
    device), so one device can never overwrite another's image. None for an unsafe segment."""
    if not all(_SAFE_ID.match(part) for part in (site, device, snapshot_id)):
        return None
    return f"{site}/{device}/{snapshot_id}.jpg"


def _safe_stored(stored: str) -> bool:
    """`<id>.jpg` (rows stored before snapshots were keyed by device) or `snapshot_key`."""
    *dirs, name = stored.split("/")
    stem, dot, ext = name.rpartition(".")
    return (
        len(dirs) in (0, 2)
        and all(_SAFE_ID.match(d) for d in dirs)
        and dot == "."
        and ext == "jpg"
        and bool(_SAFE_ID.match(stem))
    )


def snapshot_file(snapshot_dir: Path, stored: str | None) -> Path:
    """The JPEG at a row's stored snapshot path (`snapshot_path`, `before_snapshot_path`)."""
    if not stored or not _safe_stored(stored):
        raise NotFound("Imaginea nu există.")
    path = snapshot_dir / stored
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
                if e.state in LEGACY_STATES and not is_upload(e.device_id, e.camera_id):
                    out.append(AlertMessage(data=event_out(e)))
            for r in await SuggestionRepository(s).after(self._last_suggestion):
                self._last_suggestion = r.id
                if r.status == "pending":
                    out.append(SuggestionMessage(data=suggestion_out(r)))
        return out
