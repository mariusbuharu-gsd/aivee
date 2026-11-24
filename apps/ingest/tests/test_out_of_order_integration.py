"""R2: lifecycle events that arrive before their `opened` are kept and folded when it comes."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from aivee_api.alerts.audit import RepositoryAuditWriter
from aivee_api.alerts.repository import AlertRepository
from aivee_api.audit.models import AuditRow
from aivee_api.push.sender import PushKind
from aivee_contracts.events import AlertEvent
from aivee_contracts.topics import Topics
from aivee_ingest.handler import IngestHandler
from sqlalchemy import select, text

pytestmark = pytest.mark.integration

T = Topics(site="loc-r2", device="edge-r2")
T0 = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


class Recording:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        self.sent.append(f"opened:{event.event_id}")

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None, kind: PushKind
    ) -> None:
        self.sent.append(f"{kind}:{tag}")


def _event(state: str, at_s: float, zone: str = "t1") -> AlertEvent:
    return AlertEvent(
        event_id=str(uuid.uuid4()),
        rule_id="r1",
        camera_id="cam1",
        zone_id=zone,
        state=state,  # type: ignore[arg-type]
        at=T0 + timedelta(seconds=at_s),
        summary_ro="Masa 1 așteaptă",
    )


def _handler(sessions: Any, tmp_path: Path, notifier: Recording) -> IngestHandler:
    return IngestHandler(
        sessions, tmp_path, notifier, audit=RepositoryAuditWriter(), close_grace_s=0
    )


async def _send(handler: IngestHandler, *events: AlertEvent) -> None:
    for e in events:
        await handler.handle(T.events, e.model_dump_json().encode())


async def _alert_of(sessions: Any, event_id: str) -> str | None:
    async with sessions() as s:
        value = await s.scalar(
            text("SELECT alert_id FROM events WHERE event_id = :id"), {"id": event_id}
        )
    return str(value) if value is not None else None


async def test_a_closed_before_its_opened_closes_the_alert_when_it_arrives(
    sessions: Any, tmp_path: Path
) -> None:
    notifier = Recording()
    handler = _handler(sessions, tmp_path, notifier)
    opened, closed = _event("opened", 0), _event("closed", 40)
    await _send(handler, closed, opened)
    await handler.drain()

    async with sessions() as s:
        view = await AlertRepository(s).view(opened.event_id)
        kinds = list(
            await s.scalars(select(AuditRow.kind).where(AuditRow.target_id == opened.event_id))
        )
    assert view is not None and view.state == "closed" and view.closed_at == closed.at
    assert await _alert_of(sessions, closed.event_id) == opened.event_id
    assert sorted(kinds) == ["alert.closed", "alert.opened"]
    # The situation is over before anyone heard of it: nobody is rung for it.
    assert notifier.sent == []


async def test_arrived_and_closed_before_opened_fold_both(sessions: Any, tmp_path: Path) -> None:
    notifier = Recording()
    handler = _handler(sessions, tmp_path, notifier)
    opened, arrived, closed = _event("opened", 0), _event("arrived", 25), _event("closed", 30)
    await _send(handler, arrived, closed, opened)
    await handler.drain()
    async with sessions() as s:
        view = await AlertRepository(s).view(opened.event_id)
    assert view is not None and view.arrived_at == arrived.at and view.closed_at == closed.at
    assert view.wait_s == 25
    assert notifier.sent == []


async def test_an_early_close_goes_to_its_own_alert_not_the_previous_one(
    sessions: Any, tmp_path: Path
) -> None:
    notifier = Recording()
    handler = _handler(sessions, tmp_path, notifier)
    first, first_closed = _event("opened", 0), _event("closed", 10)
    second, second_closed = _event("opened", 60), _event("closed", 90)
    await _send(handler, first, first_closed, second_closed, second)
    await handler.drain()
    assert await _alert_of(sessions, first_closed.event_id) == first.event_id
    assert await _alert_of(sessions, second_closed.event_id) == second.event_id
    async with sessions() as s:
        a = await AlertRepository(s).view(first.event_id)
        b = await AlertRepository(s).view(second.event_id)
    assert a is not None and a.closed_at == first_closed.at
    assert b is not None and b.closed_at == second_closed.at


async def test_two_replicas_racing_opened_and_closed_always_link_them(
    sessions: Any, tmp_path: Path
) -> None:
    """Replica A gets the opened, replica B the closed, at the same moment."""
    a, b = _handler(sessions, tmp_path, Recording()), _handler(sessions, tmp_path, Recording())
    pairs = []
    for i in range(8):
        zone = f"z{i}"
        opened, closed = _event("opened", 0, zone), _event("closed", 20, zone)
        pairs.append((opened, closed))
        await asyncio.gather(_send(a, opened), _send(b, closed))
    await asyncio.gather(a.drain(), b.drain())
    for opened, closed in pairs:
        assert await _alert_of(sessions, closed.event_id) == opened.event_id
        async with sessions() as s:
            view = await AlertRepository(s).view(opened.event_id)
        assert view is not None and view.closed_at == closed.at
