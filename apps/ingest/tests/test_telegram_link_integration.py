"""One getUpdates poller per database: the Postgres advisory lock."""

from typing import Any

import pytest
from aivee_ingest.telegram_link import AdvisoryPollLock
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration


async def test_only_one_replica_holds_the_poll_lock(db_url: str) -> None:
    a_engine: Any = create_async_engine(db_url)
    b_engine: Any = create_async_engine(db_url)
    a, b = AdvisoryPollLock(a_engine), AdvisoryPollLock(b_engine)
    try:
        assert await a.acquire() is True
        assert await a.acquire() is True  # still ours
        assert await b.acquire() is False
        await a.release()
        assert await b.acquire() is True  # takes over
        assert await a.acquire() is False
    finally:
        await a.release()
        await b.release()
        await a_engine.dispose()
        await b_engine.dispose()


async def test_lock_is_freed_when_the_holder_disappears(db_url: str) -> None:
    a_engine: Any = create_async_engine(db_url)
    b_engine: Any = create_async_engine(db_url)
    a, b = AdvisoryPollLock(a_engine), AdvisoryPollLock(b_engine)
    try:
        assert await a.acquire() is True
        await a._conn.invalidate()  # the connection dropped: Postgres frees the lock
        assert await b.acquire() is True
        assert await a.acquire() is False  # notices the loss, finds the lock taken
    finally:
        await a.release()
        await b.release()
        await a_engine.dispose()
        await b_engine.dispose()
