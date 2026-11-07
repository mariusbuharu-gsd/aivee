"""The "Preiau ✋" ack against Postgres: the dashboard's ack path, audit, chat check, names."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aivee_api.alerts.audit import RepositoryAuditWriter
from aivee_api.alerts.repository import AlertRepository
from aivee_api.audit.models import AuditRow
from aivee_api.db.models import Camera, EventRow, RuleRow, Site
from aivee_api.db.repositories import DeviceRepository
from aivee_contracts.events import AlertEvent
from aivee_contracts.rules import Action, Condition, Rule
from aivee_ingest.alert_message import headline_explanation, render
from aivee_ingest.locations import alert_context
from aivee_ingest.telegram_ack import DbAckStore
from sqlalchemy import select

pytestmark = pytest.mark.integration

SITE, DEVICE, CHAT = "demo", "edge-01", "-100777"
NOW = datetime.now(UTC).replace(microsecond=0)


async def _seed(sessions: Any, chat: str | None = CHAT) -> None:
    from aivee_api.accounts.models import Organization

    rule = Rule(
        id="r1",
        camera_id="cam-01",
        name="Masă neservită",
        prompt_ro="anunță-mă dacă o masă e neservită 1 minut",
        zone_tag="table",
        all_of=[
            Condition(kind="present", role="guest", min_duration_s=10),
            Condition(kind="absent", role="staff", min_duration_s=60),
        ],
        action=Action(type="telegram"),
    )
    async with sessions() as s:
        s.add(Organization(id="org", name="Org"))
        await s.flush()
        s.add(Site(id=SITE, name="Terasa demo", org_id="org", telegram_chat_id=chat))
        await DeviceRepository(s).ensure_device(SITE, DEVICE)
        await s.flush()
        s.add(
            Camera(
                id="cam-01",
                device_id=DEVICE,
                name="Sala principală",
                source="rtsp://x",
                zones=[{"id": "z-mw4t3c6b", "name": "Masa 1"}],
            )
        )
        await s.flush()
        s.add(RuleRow(id="r1", camera_id="cam-01", rule=rule.model_dump(mode="json")))
        await s.commit()


async def _alert(sessions: Any, *, closed: bool = False) -> str:
    event_id = str(uuid.uuid4())
    async with sessions() as s:
        s.add(
            EventRow(
                event_id=event_id,
                device_id=DEVICE,
                rule_id="r1",
                camera_id="cam-01",
                zone_id="z-mw4t3c6b",
                state="opened",
                at=NOW - timedelta(minutes=1),
                summary_ro="Masa 1: neservită de 1 min",
                alert_id=event_id,
                closed_at=NOW if closed else None,
            )
        )
        await s.commit()
    return event_id


def _store(sessions: Any, default_chat: str | None = None) -> DbAckStore:
    return DbAckStore(sessions, RepositoryAuditWriter(), default_chat, now=lambda: NOW)


async def test_ack_from_telegram_uses_the_dashboard_path_and_is_audited(sessions: Any) -> None:
    await _seed(sessions)
    alert = await _alert(sessions)
    store = _store(sessions)

    outcome = await store.acknowledge(alert, CHAT, "Ana", "555")
    assert (outcome.status, outcome.by, outcome.at) == ("acked", "Ana", NOW)
    assert outcome.context is not None
    assert outcome.context.location_name == "Terasa demo"
    assert outcome.context.camera_name == "Sala principală"
    assert headline_explanation(outcome.context) == (
        "Masa 1 așteaptă de 1 min",
        "Nu a venit nimeni la client.",
    )

    async with sessions() as s:
        view = await AlertRepository(s).view(alert)
        audits = list(
            await s.scalars(select(AuditRow).where(AuditRow.kind == "alert.acknowledged"))
        )
    assert view is not None and view.state == "acknowledged"
    assert (view.acknowledged_by, view.acknowledged_by_id, view.acknowledged_at) == (
        "Ana",
        None,
        NOW,
    )
    [entry] = audits
    assert (entry.actor_kind, entry.actor_id, entry.actor_name) == ("user", "telegram:555", "Ana")
    assert (entry.location_id, entry.target_id, entry.after) == (SITE, alert, {"via": "telegram"})
    assert entry.summary_ro == "Ana a preluat alerta de la Masa 1"

    again = await store.acknowledge(alert, CHAT, "Mihai", "556")
    assert (again.status, again.by) == ("already", "Ana")


async def test_closed_wrong_chat_and_unknown(sessions: Any) -> None:
    await _seed(sessions)
    closed = await _alert(sessions, closed=True)
    open_ = await _alert(sessions)
    store = _store(sessions, default_chat="-100999")

    assert (await store.acknowledge(closed, CHAT, "Ana", "1")).status == "closed"
    # The location has its own chat: the default chat may not take its alerts.
    assert (await store.acknowledge(open_, "-100999", "Ana", "1")).status == "wrong_chat"
    assert (await store.acknowledge(str(uuid.uuid4()), CHAT, "Ana", "1")).status == "unknown"
    async with sessions() as s:
        view = await AlertRepository(s).view(open_)
    assert view is not None and view.acknowledged_at is None


async def test_without_a_location_chat_the_default_chat_may_take_it(sessions: Any) -> None:
    await _seed(sessions, chat=None)
    alert = await _alert(sessions)
    assert (await _store(sessions).acknowledge(alert, CHAT, "Ana", "1")).status == "wrong_chat"
    store = _store(sessions, default_chat=CHAT)
    assert (await store.acknowledge(alert, CHAT, "Ana", "1")).status == "acked"


async def test_alert_context_resolves_names_and_falls_back_to_ids(sessions: Any) -> None:
    await _seed(sessions)
    alert = await _alert(sessions)
    event = AlertEvent(
        event_id=alert,
        rule_id="r1",
        camera_id="cam-01",
        zone_id="z-mw4t3c6b",
        state="opened",
        at=NOW,
        summary_ro="Masa 1: neservită de 1 min",
    )
    text = render(await alert_context(sessions, event))
    assert "<b>Masa 1 așteaptă de 1 min</b>" in text
    assert "Terasa demo · Sala principală" in text
    assert "cam-01" not in text and "z-mw4t3c6b" not in text

    stranger = event.model_copy(
        update={"event_id": "nope", "camera_id": "cam-x", "rule_id": "gone"}
    )
    ctx = await alert_context(sessions, stranger)
    assert (ctx.camera_name, ctx.location_name, ctx.zone_name) == ("cam-x", "", "Masa 1")
    assert headline_explanation(ctx) == ("Masa 1: neservită de 1 min", "")
