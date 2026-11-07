"""Alerts manage themselves: arrival and an unserved close resolve the original message,
and an open, unreached alert is reminded every REMIND_S (once per period across replicas)."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from aivee_api.alerts.audit import RepositoryAuditWriter
from aivee_api.alerts.auth import AlertUser
from aivee_api.alerts.repository import AlertRepository
from aivee_api.alerts.schemas import AlertView
from aivee_api.db.models import Camera, EventRow, RuleRow
from aivee_api.db.repositories import DeviceRepository
from aivee_api.db.session import make_engine, make_session_factory
from aivee_api.push.sender import PushKind
from aivee_contracts.events import AlertEvent, DeviceStatus
from aivee_contracts.topics import Topics
from aivee_ingest.handler import IngestHandler
from aivee_ingest.remind import Reminder
from sqlalchemy import select

pytestmark = pytest.mark.integration

SITE, DEVICE = "demo", "edge-01"
TOPICS = Topics(site=SITE, device=DEVICE)
NOW = datetime.now(UTC).replace(microsecond=0)


class Notifier:
    """Records every channel call; implements the optional lifecycle methods."""

    def __init__(self) -> None:
        self.texts: list[tuple[str, str | None, str | None, PushKind]] = []
        self.resolved: list[tuple[str, str]] = []
        self.reminders: list[tuple[str, str]] = []

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None: ...

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None, kind: PushKind
    ) -> None:
        self.texts.append((text, tag, title, kind))

    async def alert_resolved(self, view: AlertView, line: str) -> None:
        self.resolved.append((view.event_id, line))

    async def alert_reminder(self, view: AlertView, text: str) -> None:
        self.reminders.append((view.event_id, text))


async def _seed(sessions: Any, *, visual_rule: bool = False) -> None:
    from aivee_api.accounts.models import Organization
    from aivee_api.db.models import Site

    async with sessions() as s:
        s.add(Organization(id="org", name="Org"))
        await s.flush()
        s.add(Site(id=SITE, name="Demo", org_id="org"))
        await DeviceRepository(s).ensure_device(SITE, DEVICE)
        if visual_rule:
            s.add(Camera(id="cam1", device_id=DEVICE, name="Sala", source="rtsp://x"))
            await s.flush()
            s.add(
                RuleRow(
                    id="fire",
                    camera_id="cam1",
                    rule={
                        "id": "fire",
                        "camera_id": "cam1",
                        "name": "Foc",
                        "prompt_ro": "dacă e foc",
                        "zone_tag": "table",
                        "all_of": [{"kind": "visual", "label_ro": "foc", "positive": ["fire"]}],
                        "action": {"type": "telegram"},
                    },
                )
            )
        await s.commit()


def _event(
    state: str, *, alert: str | None = None, at: datetime, rule: str = "r1", zone: str = "t1"
) -> AlertEvent:
    return AlertEvent.model_validate(
        {
            "event_id": alert if state == "opened" and alert else str(uuid.uuid4()),
            "rule_id": rule,
            "camera_id": "cam1",
            "zone_id": zone,
            "state": state,
            "at": at,
            "summary_ro": f"{zone.replace('t', 'Masa ')}: neservită de 1 min",
        }
    )


async def _publish(handler: IngestHandler, event: AlertEvent) -> None:
    await handler.handle(TOPICS.events, event.model_dump_json().encode())


def _handler(sessions: Any, tmp_path: Path, notifier: Notifier) -> IngestHandler:
    return IngestHandler(
        sessions, tmp_path, notifier, audit=RepositoryAuditWriter(), close_grace_s=0.05
    )


async def test_arrival_keeps_the_follow_up_and_resolves_the_original(
    sessions: Any, tmp_path: Path
) -> None:
    await _seed(sessions)
    n = Notifier()
    h = _handler(sessions, tmp_path, n)
    opened = _event("opened", alert="a1", at=NOW - timedelta(seconds=25))
    await _publish(h, opened)
    async with sessions() as s:
        assert await AlertRepository(s).acknowledge("a1", AlertUser("", "Ana"), NOW)
        await s.commit()
    await _publish(h, _event("arrived", at=NOW))
    await _publish(h, _event("closed", at=NOW + timedelta(seconds=5)))
    await h.drain()

    assert [t[0] for t in n.texts] == ["Un angajat a ajuns la Masa 1 după 25 s"]
    assert n.resolved == [("a1", "✅ Rezolvat · un angajat a ajuns după 25 s")]
    async with sessions() as s:
        view = await AlertRepository(s).view("a1")
    assert view is not None and view.closed_at is not None  # "Preiau" never closed it


async def test_guest_left_unserved_is_announced_and_resolved(sessions: Any, tmp_path: Path) -> None:
    await _seed(sessions)
    n = Notifier()
    h = _handler(sessions, tmp_path, n)
    await _publish(h, _event("opened", alert="a2", at=NOW - timedelta(seconds=190)))
    await _publish(h, _event("closed", at=NOW))
    await h.drain()

    assert n.texts == [
        (
            "👋 Clientul a plecat de la Masa 1 fără să fie servit (a așteptat 3 min 10 s)",
            "a2",
            "AiVee · Client plecat",
            "arrived",
        )
    ]
    assert n.resolved == [("a2", "⚪ Închisă · clientul a plecat")]


async def test_a_visual_rule_closing_by_itself_is_not_a_guest_leaving(
    sessions: Any, tmp_path: Path
) -> None:
    await _seed(sessions, visual_rule=True)
    n = Notifier()
    h = _handler(sessions, tmp_path, n)
    await _publish(h, _event("opened", alert="a3", at=NOW - timedelta(seconds=60), rule="fire"))
    await _publish(h, _event("closed", at=NOW, rule="fire"))
    await h.drain()
    assert n.texts[0][0] == "⚪ Alerta de la Masa 1 s-a închis singură după 1 min"
    assert n.resolved == [("a3", "⚪ Închisă · situația s-a încheiat")]


async def test_a_device_going_offline_resolves_its_open_alerts(
    sessions: Any, tmp_path: Path
) -> None:
    await _seed(sessions)
    n = Notifier()
    h = _handler(sessions, tmp_path, n)
    status = DeviceStatus(device=DEVICE, state="online").model_dump_json().encode()
    await h.handle(TOPICS.status, status)
    await _publish(h, _event("opened", alert="a4", at=NOW - timedelta(seconds=30)))
    offline = DeviceStatus(device=DEVICE, state="offline").model_dump_json().encode()
    await h.handle(TOPICS.status, offline)
    assert n.resolved == [("a4", "⚪ Închisă · dispozitivul s-a deconectat")]


async def test_closed_processed_before_a_late_arrival_is_not_a_guest_leaving(
    sessions: Any, tmp_path: Path
) -> None:
    await _seed(sessions)
    n = Notifier()
    h = _handler(sessions, tmp_path, n)
    await _publish(h, _event("opened", alert="a5", at=NOW - timedelta(seconds=35)))
    await _publish(h, _event("closed", at=NOW))
    await _publish(h, _event("arrived", at=NOW))  # another replica was slower
    await h.drain()
    assert [t[0] for t in n.texts] == ["Un angajat a ajuns la Masa 1 după 35 s"]
    assert n.resolved == [("a5", "✅ Rezolvat · un angajat a ajuns după 35 s")]


async def _row(sessions: Any, *, opened_ago_s: float, **kw: Any) -> str:
    event_id = str(uuid.uuid4())
    async with sessions() as s:
        s.add(
            EventRow(
                event_id=event_id,
                device_id=DEVICE,
                rule_id="r1",
                camera_id="cam1",
                zone_id="t1",
                state="opened",
                at=NOW - timedelta(seconds=opened_ago_s),
                summary_ro="Masa 1: neservită",
                alert_id=event_id,
                **kw,
            )
        )
        await s.commit()
    return event_id


async def test_reminders_every_period_until_arrival_or_close(sessions: Any) -> None:
    await _seed(sessions)
    due = await _row(sessions, opened_ago_s=250)
    later = await _row(sessions, opened_ago_s=100)  # not yet
    await _row(sessions, opened_ago_s=300, arrived_at=NOW - timedelta(seconds=10))
    await _row(sessions, opened_ago_s=300, closed_at=NOW - timedelta(seconds=10))
    acked = await _row(
        sessions,
        opened_ago_s=300,
        acknowledged_at=NOW - timedelta(seconds=200),
        acknowledged_by_name="Ana",
    )
    clock = [NOW]
    n = Notifier()
    reminder = Reminder(sessions, n, 120, now=lambda: clock[0])

    first = await reminder.tick()
    assert sorted(v.event_id for v in first) == sorted([due, acked])  # "Preiau" keeps reminding
    assert (due, "⏰ Încă neservit: Masa 1, de 4 min") in n.reminders
    assert await reminder.tick() == []  # not again within the period

    clock[0] = NOW + timedelta(seconds=121)
    async with sessions() as s:
        row = await s.scalar(select(EventRow).where(EventRow.event_id == acked))
        assert row is not None
        row.arrived_at = clock[0]
        await s.commit()
    again = await reminder.tick()
    # Arrival stopped the acked one; the younger alert is now due for its first.
    assert sorted(v.event_id for v in again) == sorted([due, later])
    assert n.reminders[-1] == (due, "⏰ Încă neservit: Masa 1, de 6 min")


async def test_reminder_falls_back_to_plain_text_for_simple_notifiers(sessions: Any) -> None:
    class Plain:
        def __init__(self) -> None:
            self.texts: list[tuple[str, str | None, PushKind]] = []

        async def notify(self, event: AlertEvent, snapshot: Path | None) -> None: ...

        async def send_text(
            self, text: str, tag: str | None = None, *, title: str | None = None, kind: PushKind
        ) -> None:
            self.texts.append((text, tag, kind))

    await _seed(sessions)
    due = await _row(sessions, opened_ago_s=130)
    plain = Plain()
    await Reminder(sessions, plain, 120, now=lambda: NOW).tick()
    assert plain.texts == [("⏰ Încă neservit: Masa 1, de 2 min", due, "realert")]


async def test_two_replicas_remind_once_per_period(sessions: Any, db_url: str) -> None:
    await _seed(sessions)
    due = await _row(sessions, opened_ago_s=130)
    engines = [make_engine(db_url), make_engine(db_url)]
    notifiers = [Notifier(), Notifier()]
    replicas = [
        Reminder(make_session_factory(e), n, 120, now=lambda: NOW)
        for e, n in zip(engines, notifiers, strict=True)
    ]
    try:
        for _ in range(5):
            await asyncio.gather(*(r.tick() for r in replicas))
    finally:
        for e in engines:
            await e.dispose()
    assert [eid for n in notifiers for eid, _ in n.reminders] == [due]
