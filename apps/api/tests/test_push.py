"""`/api/push/*` routes and the shared push fan-out. DB tests are marked integration."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from aivee_api.main import create_app
from aivee_api.push.repository import PushSubscriptionRepository
from aivee_api.push.sender import PushMessage, Subscription, WebPushSender
from aivee_api.push.service import push_to_all
from aivee_api.push.settings import VapidSettings
from aivee_api.settings import ApiSettings

VAPID = VapidSettings(public_key="BPUB", private_key="priv", subject="mailto:t@example.com")
SUB = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abc",
    "expirationTime": None,
    "keys": {"p256dh": "BKEY", "auth": "AUTH"},
}


class FakeSender:
    """Answers with a fixed status per endpoint (default 201) and records the payloads."""

    def __init__(self, statuses: dict[str, int] | None = None) -> None:
        self.statuses = statuses or {}
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def send(self, sub: Subscription, payload: str) -> int:
        self.sent.append((sub.endpoint, json.loads(payload)))
        return self.statuses.get(sub.endpoint, 201)


def _no_db() -> Any:
    raise AssertionError("this route must not touch the database")


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _app(services: Any, vapid: VapidSettings, sender: FakeSender | None = None) -> Any:
    app = create_app(services)
    app.state.vapid = vapid
    if sender is not None:
        app.state.push_sender = sender
    return app


# ---------- unit ----------


async def test_public_key_is_served(
    settings: ApiSettings, publisher: Any, translator: Any, services_factory: Any
) -> None:
    app = _app(services_factory(settings, _no_db, publisher, translator), VAPID)
    async with _client(app) as c:
        r = await c.get("/api/push/public-key")
    assert r.status_code == 200 and r.json() == {"public_key": "BPUB"}


async def test_public_key_without_vapid_is_503_in_romanian(
    settings: ApiSettings, publisher: Any, translator: Any, services_factory: Any
) -> None:
    app = _app(services_factory(settings, _no_db, publisher, translator), VapidSettings())
    async with _client(app) as c:
        r = await c.get("/api/push/public-key")
    assert r.status_code == 503
    assert "VAPID" in r.json()["detail"]["message_ro"]


def test_message_payload_is_json_with_romanian_text() -> None:
    message = PushMessage(title="Alertă", body="Masa 1 așteaptă", kind="alert")
    payload = json.loads(message.payload())
    expected = {
        "title": "Alertă",
        "body": "Masa 1 așteaptă",
        "kind": "alert",
        "url": "/alerte",
        "tag": "aivee",
    }
    assert payload == expected


def test_web_push_sender_needs_keys() -> None:
    with pytest.raises(ValueError):
        WebPushSender(VapidSettings())


# ---------- integration (real Postgres) ----------


@pytest.fixture
async def api_db(
    settings: ApiSettings,
    sessions: Any,
    publisher: Any,
    translator: Any,
    services_factory: Any,
    tenancy_factory: Any,
    login: Any,
) -> AsyncIterator[tuple[httpx.AsyncClient, FakeSender]]:
    """Logged in as staff@t.ro (location `test`)."""
    await tenancy_factory(sessions)
    sender = FakeSender()
    app = _app(services_factory(settings, sessions, publisher, translator), VAPID, sender)
    async with _client(app) as c:
        await login(c, "staff@t.ro")
        yield c, sender


@pytest.mark.integration
async def test_subscribe_is_idempotent_and_updates_keys(
    api_db: tuple[httpx.AsyncClient, FakeSender], sessions: Any
) -> None:
    c, _ = api_db
    assert (await c.post("/api/push/subscribe", json=SUB)).status_code == 201
    rotated = {**SUB, "keys": {"p256dh": "BNEW", "auth": "AUTH2"}}
    assert (await c.post("/api/push/subscribe", json=rotated)).status_code == 201
    async with sessions() as s:
        subs = await PushSubscriptionRepository(s).all()
    assert subs == [Subscription(SUB["endpoint"], "BNEW", "AUTH2")]  # type: ignore[arg-type]


@pytest.mark.integration
async def test_subscribe_rejects_a_non_https_endpoint(
    api_db: tuple[httpx.AsyncClient, FakeSender],
) -> None:
    c, _ = api_db
    r = await c.post("/api/push/subscribe", json={**SUB, "endpoint": "http://169.254.169.254/x"})
    assert r.status_code == 422


@pytest.mark.integration
async def test_unsubscribe_removes_and_is_idempotent(
    api_db: tuple[httpx.AsyncClient, FakeSender], sessions: Any
) -> None:
    c, _ = api_db
    await c.post("/api/push/subscribe", json=SUB)
    for _ in range(2):
        r = await c.request("DELETE", "/api/push/subscribe", json={"endpoint": SUB["endpoint"]})
        assert r.status_code == 204
    async with sessions() as s:
        assert await PushSubscriptionRepository(s).all() == []


@pytest.mark.integration
async def test_test_push_reaches_the_users_subscriptions(
    api_db: tuple[httpx.AsyncClient, FakeSender],
) -> None:
    c, sender = api_db
    await c.post("/api/push/subscribe", json=SUB)
    await c.post("/api/push/subscribe", json={**SUB, "endpoint": "https://push.example/2"})
    r = await c.post("/api/push/test")
    assert r.status_code == 200 and r.json() == {"sent": 2, "removed": 0, "failed": 0}
    assert {e for e, _ in sender.sent} == {SUB["endpoint"], "https://push.example/2"}
    assert sender.sent[0][1]["url"] == "/alerte"


@pytest.mark.integration
async def test_push_routes_need_a_login(
    settings: ApiSettings, sessions: Any, publisher: Any, translator: Any, services_factory: Any
) -> None:
    app = _app(services_factory(settings, sessions, publisher, translator), VAPID, FakeSender())
    async with _client(app) as c:
        assert (await c.post("/api/push/subscribe", json=SUB)).status_code == 401
        assert (await c.post("/api/push/test")).status_code == 401
        r = await c.request("DELETE", "/api/push/subscribe", json={"endpoint": "https://x"})
        assert r.status_code == 401


@pytest.mark.integration
async def test_subscription_belongs_to_the_user_and_alerts_reach_only_the_location(
    api_db: tuple[httpx.AsyncClient, FakeSender], sessions: Any, client_factory: Any, login: Any
) -> None:
    from aivee_api.push.service import push_to_location

    staff, sender = api_db
    await staff.post("/api/push/subscribe", json=SUB)  # staff@t.ro → `test`
    async with sessions() as s:
        repo = PushSubscriptionRepository(s)
        await repo.upsert(Subscription("https://p/owner", "k", "a"), user_id="u-owner")
        await repo.upsert(Subscription("https://p/other", "k", "a"), user_id="u-other")
        await repo.upsert(Subscription("https://p/xowner", "k", "a"), user_id="u-xowner")
        await repo.upsert(Subscription("https://p/anon", "k", "a"))
        await s.commit()

    msg = PushMessage(title="t", body="b", kind="test")
    await push_to_location(sessions, sender, msg, "test")
    assert {e for e, _ in sender.sent} == {SUB["endpoint"], "https://p/owner"}
    sender.sent.clear()
    await push_to_location(sessions, sender, msg, "far")
    assert {e for e, _ in sender.sent} == {"https://p/xowner"}

    # the test push reaches only the caller's own devices; others' endpoints are not theirs
    sender.sent.clear()
    assert (await staff.post("/api/push/test")).json()["sent"] == 1
    assert [e for e, _ in sender.sent] == [SUB["endpoint"]]
    assert sender.sent[0][1]["kind"] == "test"
    r = await staff.request("DELETE", "/api/push/subscribe", json={"endpoint": "https://p/owner"})
    assert r.status_code == 204
    async with sessions() as s:
        assert len(await PushSubscriptionRepository(s).for_user("u-owner")) == 1


@pytest.mark.integration
async def test_push_to_all_drops_gone_subscriptions(sessions: Any) -> None:
    async with sessions() as s:
        repo = PushSubscriptionRepository(s)
        for endpoint in ("https://p/ok", "https://p/gone", "https://p/expired", "https://p/err"):
            await repo.upsert(Subscription(endpoint, "k", "a"))
        await s.commit()
    sender = FakeSender({"https://p/gone": 410, "https://p/expired": 404, "https://p/err": 500})
    report = await push_to_all(sessions, sender, PushMessage(title="t", body="b", kind="test"))
    assert (report.sent, report.removed, report.failed) == (1, 2, 1)
    async with sessions() as s:
        left = {sub.endpoint for sub in await PushSubscriptionRepository(s).all()}
    assert left == {"https://p/ok", "https://p/err"}


@pytest.mark.integration
async def test_push_to_all_without_subscriptions_sends_nothing(sessions: Any) -> None:
    sender = FakeSender()
    report = await push_to_all(sessions, sender, PushMessage(title="t", body="b", kind="test"))
    assert report.sent == 0 and sender.sent == []
