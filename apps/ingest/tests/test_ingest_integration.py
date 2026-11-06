"""Edge → Mosquitto → ingest → Postgres, with the production ACL."""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from aivee_api.db.repositories import DeviceRepository
from aivee_contracts.events import AlertEvent, StaffSuggestion
from aivee_edge.adapters.mqtt import MqttEdgeClient
from aivee_ingest.config import IngestSettings
from aivee_ingest.handler import IngestHandler
from aivee_ingest.worker import run_worker
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


class RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[AlertEvent, Path | None]] = []

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        self.calls.append((event, snapshot))


def _event(state: str = "opened") -> AlertEvent:
    return AlertEvent.model_validate(
        {
            "event_id": str(uuid.uuid4()),
            "rule_id": "r1",
            "camera_id": "cam1",
            "zone_id": "t1",
            "state": state,
            "at": datetime.now(UTC),
            "summary_ro": "Masa 1 așteaptă",
        }
    )


async def _until(cond: Callable[[], Any], timeout: float = 10) -> None:
    async def poll() -> None:
        while not await cond():
            await asyncio.sleep(0.1)

    await asyncio.wait_for(poll(), timeout)


@contextlib.asynccontextmanager
async def _workers(
    broker: Any, sessions: async_sessionmaker[AsyncSession], tmp: Path, n: int
) -> AsyncIterator[list[tuple[IngestHandler, RecordingNotifier]]]:
    user, password = broker.ingest
    out, tasks = [], []
    for i in range(n):
        notifier = RecordingNotifier()
        handler = IngestHandler(sessions, tmp, notifier)
        settings = IngestSettings(
            mqtt_host=broker.host,
            mqtt_port=broker.port,
            mqtt_ingest_user=user,
            mqtt_ingest_password=password,
            mqtt_client_id=f"ingest-test-{i}-{uuid.uuid4().hex[:6]}",
        )
        ready = asyncio.Event()
        tasks.append(asyncio.create_task(run_worker(settings, handler, ready)))
        await asyncio.wait_for(ready.wait(), 10)
        out.append((handler, notifier))
    try:
        yield out
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _edge(broker: Any, site: str) -> MqttEdgeClient:
    user, password = broker.edge
    edge = MqttEdgeClient(broker.host, broker.port, user, password, site, user, keepalive=5)
    await asyncio.to_thread(edge.start)
    return edge


async def _count(sessions: async_sessionmaker[AsyncSession], sql: str) -> int:
    async with sessions() as s:
        return int(await s.scalar(text(sql)) or 0)


async def _events_are(sessions: async_sessionmaker[AsyncSession], n: int) -> bool:
    return await _count(sessions, "SELECT count(*) FROM events") == n


async def test_event_with_snapshot_is_stored_once_and_notified(
    broker: Any, sessions: async_sessionmaker[AsyncSession], site: str, tmp_path: Path
) -> None:
    async with _workers(broker, sessions, tmp_path, 1) as [(_, notifier)]:
        edge = await _edge(broker, site)
        event = _event()
        edge.publish_alert(event, b"\xff\xd8blurred")
        edge.publish_alert(event, b"\xff\xd8blurred")  # redelivery / duplicate
        edge.publish_alert(_event(state="closed"), None)

        await _until(lambda: _events_are(sessions, 2))
        await asyncio.sleep(0.5)
        await asyncio.to_thread(edge.stop)

    assert await _count(sessions, "SELECT count(*) FROM events") == 2
    (notified, snapshot) = notifier.calls[0]
    assert len(notifier.calls) == 1 and notified.event_id == event.event_id
    assert snapshot is not None and snapshot.read_bytes() == b"\xff\xd8blurred"
    async with sessions() as s:
        path = await s.scalar(
            text("SELECT snapshot_path FROM events WHERE event_id = :id"), {"id": event.event_id}
        )
    assert path == f"{event.event_id}.jpg"


async def test_suggestion_crop_is_stored_like_an_event_snapshot(
    broker: Any, sessions: async_sessionmaker[AsyncSession], site: str, tmp_path: Path
) -> None:
    """The API learns a confirmed suggestion from SNAPSHOT_DIR/<suggestion_id>.jpg."""
    suggestion = StaffSuggestion(
        suggestion_id=str(uuid.uuid4()),
        camera_id="cam1",
        track_id=7,
        staff_score=0.8,
        reason_ro="vizitează 3 mese",
    )
    async with _workers(broker, sessions, tmp_path, 1):
        edge = await _edge(broker, site)
        edge.publish_suggestion(suggestion, b"\xff\xd8person")

        async def stored() -> bool:
            n = await _count(sessions, "SELECT count(*) FROM suggestions")
            return n == 1 and (tmp_path / f"{suggestion.suggestion_id}.jpg").is_file()

        await _until(stored)
        await asyncio.to_thread(edge.stop)

    assert (tmp_path / f"{suggestion.suggestion_id}.jpg").read_bytes() == b"\xff\xd8person"


async def test_last_will_marks_device_offline(
    broker: Any, sessions: async_sessionmaker[AsyncSession], site: str, tmp_path: Path
) -> None:
    async def state() -> str | None:
        async with sessions() as s:
            device = await DeviceRepository(s).get(broker.edge[0])
            return device.state if device else None

    async with _workers(broker, sessions, tmp_path, 1):
        edge = await _edge(broker, site)
        await _until(lambda: _is(state, "online"))
        edge._client.loop_stop()  # crash: no DISCONNECT, broker fires the will
        sock = edge._client.socket()
        assert sock is not None
        sock.close()
        await _until(lambda: _is(state, "offline"))


async def _is(getter: Callable[[], Any], value: Any) -> bool:
    return bool(await getter() == value)


async def test_two_workers_split_the_shared_event_stream(
    broker: Any, sessions: async_sessionmaker[AsyncSession], site: str, tmp_path: Path
) -> None:
    n = 40
    async with _workers(broker, sessions, tmp_path, 2) as workers:
        edge = await _edge(broker, site)
        events = [_event() for _ in range(n)]
        for e in events:
            edge.publish_alert(e, None)
        await _until(lambda: _events_are(sessions, n))
        await asyncio.sleep(0.5)
        await asyncio.to_thread(edge.stop)

    handled = [set(h.handled_events) for h, _ in workers]
    ours = {e.event_id for e in events}
    a, b = (h & ours for h in handled)
    assert a and b, "both workers should get part of the stream"
    assert not a & b, "no event may be processed by both workers"
    assert a | b == ours
    assert sum(len(h.handled_events) for h, _ in workers) == n
