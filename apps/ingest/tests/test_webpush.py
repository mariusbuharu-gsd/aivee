import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from aivee_api.db.repositories import CameraRepository
from aivee_api.push.repository import PushSubscriptionRepository
from aivee_api.push.sender import Subscription
from aivee_api.push.settings import VapidSettings
from aivee_contracts.events import AlertEvent
from aivee_contracts.geometry import CameraConfig, Zone
from aivee_ingest.__main__ import build_notifier
from aivee_ingest.config import IngestSettings
from aivee_ingest.notify import LogNotifier
from aivee_ingest.webpush import CompositeNotifier, WebPushNotifier

EVENT = AlertEvent(
    event_id="e1",
    rule_id="r1",
    camera_id="cam1",
    zone_id="t1",
    state="opened",
    at=datetime(2026, 11, 6, 12, 30, tzinfo=UTC),
    summary_ro="Masa așteaptă de 5 minute",
)
VAPID = VapidSettings(public_key="BPUB", private_key="priv")


class FakeSender:
    def __init__(self, statuses: dict[str, int] | None = None) -> None:
        self.statuses = statuses or {}
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def send(self, sub: Subscription, payload: str) -> int:
        self.sent.append((sub.endpoint, json.loads(payload)))
        return self.statuses.get(sub.endpoint, 201)


class Recording:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        self.calls.append(event.event_id)
        if self.fail:
            raise RuntimeError("boom")

    async def send_text(self, text: str, tag: str | None = None) -> None:
        self.calls.append(f"{tag}:{text}")
        if self.fail:
            raise RuntimeError("boom")


# ---------- unit ----------


async def test_composite_keeps_going_when_one_notifier_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken, ok = Recording(fail=True), Recording()
    await CompositeNotifier([broken, ok]).notify(EVENT, None)
    assert broken.calls == ["e1"] and ok.calls == ["e1"]
    assert "Recording failed for event e1" in caplog.text


async def test_composite_sends_follow_up_text_to_every_notifier(
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken, ok = Recording(fail=True), Recording()
    await CompositeNotifier([broken, ok]).send_text("Ana a ajuns la Masa 1 după 40 s", "e1")
    assert broken.calls == ok.calls == ["e1:Ana a ajuns la Masa 1 după 40 s"]
    assert "Recording failed" in caplog.text


def test_build_notifier_adds_web_push_only_with_vapid_keys() -> None:
    settings = IngestSettings(telegram_bot_token=None, telegram_chat_id=None)
    sessions: Any = object()
    assert isinstance(build_notifier(settings, sessions, VapidSettings()), LogNotifier)
    both = build_notifier(settings, sessions, VAPID)
    assert isinstance(both, CompositeNotifier)
    assert [type(n) for n in both.notifiers] == [LogNotifier, WebPushNotifier]


# ---------- integration (real Postgres) ----------


async def _seed(sessions: Any, *endpoints: str) -> None:
    """cam1 on edge-01 at location `demo`; the endpoints belong to a staff member of `demo`.
    An outsider (member of `elsewhere`) is also subscribed and must never get demo's alerts."""
    from aivee_api.accounts.models import Membership, Organization, User
    from aivee_api.db.models import Site
    from aivee_api.db.repositories import DeviceRepository

    async with sessions() as s:
        s.add(Organization(id="org", name="Org"))
        s.add_all(
            [
                Site(id="demo", name="Demo", org_id="org"),
                Site(id="elsewhere", name="Alta", org_id="org"),
            ]
        )
        await s.flush()
        for uid, loc in (("u-ana", "demo"), ("u-out", "elsewhere")):
            s.add(User(id=uid, org_id="org", email=f"{uid}@x.ro", name=uid, password_hash="x"))
            await s.flush()
            s.add(Membership(user_id=uid, location_id=loc, role="staff"))
        await DeviceRepository(s).ensure_device("demo", "edge-01")
        await CameraRepository(s).upsert(
            CameraConfig(
                id="cam1",
                name="Sala",
                source="rtsp://x",
                zones=[Zone(id="t1", name="Masa 1", tag="table", polygon=[(0, 0), (1, 0), (1, 1)])],
            ),
            "edge-01",
        )
        repo = PushSubscriptionRepository(s)
        for endpoint in endpoints:
            await repo.upsert(Subscription(endpoint, "k", "a"), user_id="u-ana")
        await repo.upsert(Subscription("https://p/outsider", "k", "a"), user_id="u-out")
        await s.commit()


@pytest.mark.integration
async def test_web_push_sends_summary_and_zone_name_and_opens_alerts(sessions: Any) -> None:
    await _seed(sessions, "https://p/1", "https://p/2")
    sender = FakeSender()
    await WebPushNotifier(sessions, sender).notify(EVENT, None)
    assert {e for e, _ in sender.sent} == {"https://p/1", "https://p/2"}
    msg = sender.sent[0][1]
    assert msg["title"] == "Alertă AiVee · Masa 1"
    assert msg["body"] == "Masa așteaptă de 5 minute"
    assert msg["url"] == "/alerte" and msg["tag"] == "e1"


@pytest.mark.integration
async def test_web_push_falls_back_to_zone_id_for_unknown_zone(sessions: Any) -> None:
    await _seed(sessions, "https://p/1")
    sender = FakeSender()
    await WebPushNotifier(sessions, sender).notify(EVENT.model_copy(update={"zone_id": "z9"}), None)
    assert sender.sent[0][1]["title"] == "Alertă AiVee · z9"


@pytest.mark.integration
async def test_web_push_drops_expired_subscriptions(sessions: Any) -> None:
    await _seed(sessions, "https://p/ok", "https://p/gone", "https://p/404")
    sender = FakeSender({"https://p/gone": 410, "https://p/404": 404})
    await WebPushNotifier(sessions, sender).notify(EVENT, None)
    async with sessions() as s:
        left = [sub.endpoint for sub in await PushSubscriptionRepository(s).for_user("u-ana")]
    assert left == ["https://p/ok"]


@pytest.mark.integration
async def test_web_push_without_subscriptions_sends_nothing(sessions: Any) -> None:
    await _seed(sessions)
    sender = FakeSender()
    await WebPushNotifier(sessions, sender).notify(EVENT, None)
    assert sender.sent == []


@pytest.mark.integration
async def test_web_push_follow_up_replaces_the_alert_notification(sessions: Any) -> None:
    await _seed(sessions, "https://p/1")
    sender = FakeSender()
    await WebPushNotifier(sessions, sender).send_text("Ana a ajuns la Masa 1 după 40 s", "e1")
    [(_, msg)] = sender.sent
    assert msg["title"] == "AiVee · Angajat sosit"
    assert msg["body"] == "Ana a ajuns la Masa 1 după 40 s"
    assert msg["url"] == "/alerte" and msg["tag"] == "e1"


@pytest.mark.integration
async def test_web_push_for_a_camera_without_location_sends_nothing(sessions: Any) -> None:
    await _seed(sessions, "https://p/1")
    sender = FakeSender()
    await WebPushNotifier(sessions, sender).notify(
        EVENT.model_copy(update={"camera_id": "x"}), None
    )
    assert sender.sent == []
