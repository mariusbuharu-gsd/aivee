"""Re-alert the shift when nobody arrives REALERT_AFTER_S after "Merg eu" (roadmap P0.4).

Both ingest replicas run the loop, so the claim (UPDATE ... WHERE realerted_at IS NULL
RETURNING) must make each alert re-alert exactly once, with one audit entry.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from aivee_api.alerts.audit import RepositoryAuditWriter
from aivee_api.alerts.live import AlertFeed
from aivee_api.audit.models import AuditRow
from aivee_api.db.models import EventRow
from aivee_api.db.repositories import DeviceRepository
from aivee_api.db.session import make_engine, make_session_factory
from aivee_contracts.events import AlertEvent
from aivee_ingest.realert import Realerter
from sqlalchemy import select

pytestmark = pytest.mark.integration

SITE, DEVICE = "demo", "edge-01"
NOW = datetime.now(UTC).replace(microsecond=0)
AFTER_S = 120


class Notifier:
    def __init__(self) -> None:
        self.texts: list[tuple[str, str | None, str | None]] = []

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        raise AssertionError("a re-alert is a follow-up, not a new alert")

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None
    ) -> None:
        self.texts.append((text, tag, title))


async def _seed(sessions: Any) -> None:
    from aivee_api.accounts.models import Organization
    from aivee_api.db.models import Site

    async with sessions() as s:
        s.add(Organization(id="org", name="Org"))
        await s.flush()
        s.add(Site(id=SITE, name="Demo", org_id="org"))
        await DeviceRepository(s).ensure_device(SITE, DEVICE)
        await s.commit()


async def _alert(
    sessions: Any,
    zone: str,
    *,
    acked_ago_s: float | None,
    arrived: bool = False,
    closed: bool = False,
) -> str:
    event_id = str(uuid.uuid4())
    acked = NOW - timedelta(seconds=acked_ago_s) if acked_ago_s is not None else None
    async with sessions() as s:
        s.add(
            EventRow(
                event_id=event_id,
                device_id=DEVICE,
                rule_id="r1",
                camera_id="cam1",
                zone_id=zone,
                state="opened",
                at=NOW - timedelta(minutes=10),
                summary_ro=f"{zone.replace('t', 'Masa ')}: neservită de 2 min",
                alert_id=event_id,
                acknowledged_at=acked,
                acknowledged_by_name="Ana" if acked else None,
                arrived_at=NOW - timedelta(seconds=5) if arrived else None,
                closed_at=NOW - timedelta(seconds=5) if closed else None,
            )
        )
        await s.commit()
    return event_id


def _realerter(sessions: Any, notifier: Notifier) -> Realerter:
    return Realerter(sessions, notifier, RepositoryAuditWriter(), AFTER_S, now=lambda: NOW)


async def _audits(sessions: Any) -> list[AuditRow]:
    async with sessions() as s:
        return list(await s.scalars(select(AuditRow).where(AuditRow.kind == "alert.realerted")))


async def test_selects_only_unfulfilled_acks_older_than_the_delay_and_only_once(
    sessions: Any,
) -> None:
    await _seed(sessions)
    due = await _alert(sessions, "t4", acked_ago_s=121)
    await _alert(sessions, "t5", acked_ago_s=119)
    await _alert(sessions, "t6", acked_ago_s=300, arrived=True)
    await _alert(sessions, "t7", acked_ago_s=300, closed=True)
    await _alert(sessions, "t8", acked_ago_s=None)
    feed = AlertFeed(sessions)
    await feed.start()
    notifier = Notifier()
    realerter = _realerter(sessions, notifier)

    views = await realerter.tick()
    assert [v.event_id for v in views] == [due]
    assert views[0].realerted_at == NOW
    assert notifier.texts == [
        (
            "Masa 4: Ana a confirmat acum 2 min, încă nu a ajuns nimeni",
            due,
            "AiVee · Nu a ajuns nimeni",
        )
    ]
    assert await realerter.tick() == []  # once
    assert len(notifier.texts) == 1

    [entry] = await _audits(sessions)
    assert (entry.actor_kind, entry.target_id, entry.location_id) == ("system", due, SITE)

    # /ws/events gets the updated view.
    [message] = await feed.poll()
    assert (message.data.event_id, message.data.realerted_at) == (due, NOW)
    assert await feed.poll() == []


async def test_two_replicas_racing_notify_exactly_once(sessions: Any, db_url: str) -> None:
    await _seed(sessions)
    due = await _alert(sessions, "t4", acked_ago_s=121)
    # Each replica has its own engine (own connections), as in production.
    engines = [make_engine(db_url), make_engine(db_url)]
    notifiers = [Notifier(), Notifier()]
    replicas = [
        _realerter(make_session_factory(e), n) for e, n in zip(engines, notifiers, strict=True)
    ]
    try:
        for _ in range(5):
            await asyncio.gather(*(r.tick() for r in replicas))
    finally:
        for e in engines:
            await e.dispose()

    texts = [t for n in notifiers for t in n.texts]
    assert [tag for _, tag, _ in texts] == [due]
    assert len(await _audits(sessions)) == 1
