"""A device that goes offline (LWT or graceful) closes its open alerts as the system.

Both ingest replicas see every status message, so the close, its audit entries and the
one-line note per device must happen once. The edge restarts with a fresh engine: when it
comes back online after an offline ingest missed, nothing stale stays open either.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from aivee_api.alerts.audit import RepositoryAuditWriter
from aivee_api.alerts.repository import AlertRepository
from aivee_api.audit.models import AuditRow
from aivee_api.db.models import Device, EventRow
from aivee_api.push.sender import PushKind
from aivee_contracts.events import AlertEvent, DeviceStatus
from aivee_contracts.topics import Topics
from aivee_ingest.handler import IngestHandler
from sqlalchemy import select, update

pytestmark = pytest.mark.integration

SITE, DEVICE = "demo", "edge-01"
TOPICS = Topics(site=SITE, device=DEVICE)


class Notifier:
    def __init__(self) -> None:
        self.opened: list[str] = []
        self.texts: list[tuple[str, str | None, str | None, PushKind]] = []

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        self.opened.append(event.event_id)

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None, kind: PushKind
    ) -> None:
        self.texts.append((text, tag, title, kind))


def _status(state: str) -> bytes:
    return DeviceStatus(device=DEVICE, state=state).model_dump_json().encode()  # type: ignore[arg-type]


def _event(state: str, zone: str, *, event_id: str | None = None, ago_s: float = 0) -> AlertEvent:
    return AlertEvent.model_validate(
        {
            "event_id": event_id or str(uuid.uuid4()),
            "rule_id": "r1",
            "camera_id": "cam1",
            "zone_id": zone,
            "state": state,
            "at": datetime.now(UTC) - timedelta(seconds=ago_s),
            "summary_ro": f"{zone.replace('t', 'Masa ')}: neservită de 1 min",
        }
    )


async def _seed(sessions: Any) -> None:
    from aivee_api.accounts.models import Organization
    from aivee_api.db.models import Site

    async with sessions() as s:
        s.add(Organization(id="org", name="Org"))
        await s.flush()
        s.add(Site(id=SITE, name="Demo", org_id="org"))
        await s.commit()


def _replicas(sessions: Any, tmp_path: Path) -> tuple[list[IngestHandler], list[Notifier]]:
    notifiers = [Notifier(), Notifier()]
    handlers = [
        IngestHandler(sessions, tmp_path, n, audit=RepositoryAuditWriter()) for n in notifiers
    ]
    return handlers, notifiers


async def _publish(handler: IngestHandler, event: AlertEvent) -> None:
    await handler.handle(TOPICS.events, event.model_dump_json().encode())


async def _closed_audit(sessions: Any) -> list[AuditRow]:
    async with sessions() as s:
        rows = await s.scalars(
            select(AuditRow).where(AuditRow.kind == "alert.closed").order_by(AuditRow.id)
        )
        return list(rows.all())


async def _views(sessions: Any) -> dict[str, Any]:
    async with sessions() as s:
        return {v.event_id: v for v in await AlertRepository(s).views(limit=50)}


async def test_offline_closes_open_and_acknowledged_alerts_once(
    sessions: Any, tmp_path: Path
) -> None:
    await _seed(sessions)
    (a, b), notifiers = _replicas(sessions, tmp_path)
    await asyncio.gather(
        a.handle(TOPICS.status, _status("online")), b.handle(TOPICS.status, _status("online"))
    )

    waiting, acked = _event("opened", "t1", ago_s=90), _event("opened", "t2", ago_s=80)
    finished = _event("opened", "t3", ago_s=120)
    for event in (waiting, acked, finished, _event("closed", "t3", ago_s=30)):
        await _publish(a, event)
    async with sessions() as s:
        await s.execute(
            update(EventRow)
            .where(EventRow.event_id == acked.event_id)
            .values(acknowledged_at=datetime.now(UTC), acknowledged_by_name="Ana")
        )
        await s.commit()
    async with sessions() as s:
        cursor = (await AlertRepository(s).alert_ids_after(0))[0]

    # LWT: both replicas get it at the same time; then the retained copy again.
    await asyncio.gather(
        a.handle(TOPICS.status, _status("offline")), b.handle(TOPICS.status, _status("offline"))
    )
    await b.handle(TOPICS.status, _status("offline"))

    views = await _views(sessions)
    for alert in (waiting, acked):
        view = views[alert.event_id]
        assert view.state == "closed" and view.closed_at is not None
        assert (view.closed_by, view.closed_reason) == ("system", "device_offline")
        assert view.arrived_at is None
    assert views[acked.event_id].acknowledged_by == "Ana"
    old = views[finished.event_id]
    assert (old.closed_by, old.closed_reason) == ("edge", None)

    rows = await _closed_audit(sessions)
    system = [r for r in rows if r.actor_kind == "system"]
    assert sorted(r.target_id for r in system) == sorted([waiting.event_id, acked.event_id])
    assert {r.summary_ro for r in system} == {
        "Alerta de la Masa 1 s-a închis: dispozitivul s-a deconectat",
        "Alerta de la Masa 2 s-a închis: dispozitivul s-a deconectat",
    }
    assert all(r.location_id == SITE and r.org_id == "org" for r in system)
    assert all(r.after == {"reason": "device_offline"} for r in system)

    texts = [t for n in notifiers for t in n.texts]
    assert len(texts) == 1
    text, tag, title, kind = texts[0]
    assert text == "edge-01 s-a deconectat — 2 alerte închise"
    assert tag in {waiting.event_id, acked.event_id} and title
    assert kind == "device"
    assert not any("a ajuns" in t for t, _, _, _ in texts)

    # The live feed (/ws/events) sees both alerts change.
    async with sessions() as s:
        _, changed = await AlertRepository(s).alert_ids_after(cursor)
    assert sorted(changed) == sorted([waiting.event_id, acked.event_id])


async def test_offline_without_open_alerts_says_nothing(sessions: Any, tmp_path: Path) -> None:
    await _seed(sessions)
    (a, _), notifiers = _replicas(sessions, tmp_path)
    await a.handle(TOPICS.status, _status("online"))
    await a.handle(TOPICS.status, _status("offline"))
    assert await _closed_audit(sessions) == []
    assert all(n.texts == [] for n in notifiers)


async def test_one_alert_is_singular(sessions: Any, tmp_path: Path) -> None:
    await _seed(sessions)
    (a, _), notifiers = _replicas(sessions, tmp_path)
    await a.handle(TOPICS.status, _status("online"))
    await _publish(a, _event("opened", "t1"))
    await a.handle(TOPICS.status, _status("offline"))
    assert [t for t, _, _, _ in notifiers[0].texts] == ["edge-01 s-a deconectat — o alertă închisă"]


async def test_back_online_closes_stale_alerts_but_retained_online_does_not(
    sessions: Any, tmp_path: Path
) -> None:
    await _seed(sessions)
    (a, b), notifiers = _replicas(sessions, tmp_path)
    await a.handle(TOPICS.status, _status("online"))
    live = _event("opened", "t1", ago_s=10)
    await _publish(a, live)

    # An ingest restart re-reads the retained `online`: the device never left, keep it open.
    await b.handle(TOPICS.status, _status("online"))
    assert (await _views(sessions))[live.event_id].state == "opened"

    # The offline was processed before a late event, so that alert is still open...
    async with sessions() as s:
        await s.execute(update(Device).where(Device.id == DEVICE).values(state="offline"))
        await s.commit()
    # ...and the edge comes back with a fresh engine: it can never close it.
    await asyncio.gather(
        a.handle(TOPICS.status, _status("online")), b.handle(TOPICS.status, _status("online"))
    )
    view = (await _views(sessions))[live.event_id]
    assert (view.state, view.closed_by, view.closed_reason) == (
        "closed",
        "system",
        "device_restarted",
    )
    [row] = await _closed_audit(sessions)
    assert row.summary_ro == "Alerta de la Masa 1 s-a închis: dispozitivul a repornit"
    texts = [t for n in notifiers for t, _, _, _ in n.texts]
    assert texts == ["edge-01 a repornit — o alertă închisă"]


async def test_late_edge_close_after_system_close_keeps_the_system_close(
    sessions: Any, tmp_path: Path
) -> None:
    await _seed(sessions)
    (a, _), _ = _replicas(sessions, tmp_path)
    await a.handle(TOPICS.status, _status("online"))
    opened = _event("opened", "t1", ago_s=10)
    await _publish(a, opened)
    await a.handle(TOPICS.status, _status("offline"))
    await _publish(a, _event("closed", "t1"))
    view = (await _views(sessions))[opened.event_id]
    assert (view.closed_by, view.closed_reason) == ("system", "device_offline")
    assert len(await _closed_audit(sessions)) == 1
