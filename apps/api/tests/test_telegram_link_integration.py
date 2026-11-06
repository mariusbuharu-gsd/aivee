""" "Conectează Telegram": link creation, permissions, TTL, single use, status, audit.

The bot side is simulated with `consume_link` (what the ingest poller calls); no request
ever reaches api.telegram.org."""

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from aivee_api.audit.models import AuditRow
from aivee_api.db.models import Site, TelegramLinkRow
from aivee_api.deps import Services
from aivee_api.locations.telegram import StaticBotUsername, consume_link
from sqlalchemy import func, select

pytestmark = pytest.mark.integration


@pytest.fixture
def services(
    settings: Any, sessions: Any, publisher: Any, translator: Any, services_factory: Any
) -> Services:
    svc: Services = services_factory(settings, sessions, publisher, translator)
    svc.telegram_bot = StaticBotUsername("aivee_test_bot")
    return svc


@pytest.fixture
async def t(sessions: Any, tenancy_factory: Any) -> Any:
    return await tenancy_factory(sessions)


async def _as(client_factory: Any, login: Any, email: str) -> httpx.AsyncClient:
    c: httpx.AsyncClient = client_factory()
    await login(c, email)
    return c


async def _link(c: httpx.AsyncClient, location: str = "test") -> str:
    r = await c.post(f"/api/locations/{location}/telegram/link")
    assert r.status_code == 200, r.text
    query = parse_qs(urlparse(r.json()["url"]).query)
    return query["startgroup"][0]


async def _consume(sessions: Any, code: str, chat: str = "-1001", title: str = "Ospătari") -> Any:
    async with sessions() as s:
        return await consume_link(s, code, chat, title)


async def test_owner_gets_a_group_and_a_private_link(
    t: Any, client_factory: Any, login: Any, sessions: Any
) -> None:
    owner = await _as(client_factory, login, "owner@t.ro")
    r = await owner.post("/api/locations/test/telegram/link")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"url", "private_url", "expires_at"}
    url, private = urlparse(body["url"]), urlparse(body["private_url"])
    assert (url.scheme, url.netloc, url.path) == ("https", "t.me", "/aivee_test_bot")
    code = parse_qs(url.query)["startgroup"][0]
    assert parse_qs(private.query) == {"start": [code]}
    assert 8 <= len(code) <= 64 and code.replace("-", "").replace("_", "").isalnum()
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(minutes=14) < expires - datetime.now(UTC) <= timedelta(minutes=15)
    async with sessions() as s:
        row = await s.scalar(select(TelegramLinkRow))
        assert row is not None
        assert row.token_hash != code and len(row.token_hash) == 64  # only the hash is stored
        assert (row.location_id, row.created_by_id, row.used_at) == ("test", "u-owner", None)


@pytest.mark.parametrize(
    ("email", "location", "status"),
    [
        ("manager@t.ro", "test", 403),
        ("staff@t.ro", "test", 403),
        ("other@t.ro", "test", 404),
        ("owner@x.ro", "test", 404),
        ("owner@t.ro", "missing", 404),
    ],
)
async def test_link_and_status_need_locations_manage(
    t: Any, client_factory: Any, login: Any, sessions: Any, email: str, location: str, status: int
) -> None:
    c = await _as(client_factory, login, email)
    assert (await c.post(f"/api/locations/{location}/telegram/link")).status_code == status
    assert (await c.get(f"/api/locations/{location}/telegram")).status_code == status
    async with sessions() as s:
        assert await s.scalar(select(func.count()).select_from(TelegramLinkRow)) == 0


async def test_no_cookie_is_401(t: Any, api: httpx.AsyncClient) -> None:
    assert (await api.post("/api/locations/test/telegram/link")).status_code == 401
    assert (await api.get("/api/locations/test/telegram")).status_code == 401


async def test_without_a_bot_username_the_link_is_503(
    t: Any, client_factory: Any, login: Any, services: Services
) -> None:
    services.telegram_bot = StaticBotUsername(None)
    owner = await _as(client_factory, login, "owner@t.ro")
    r = await owner.post("/api/locations/test/telegram/link")
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "unavailable"


async def test_start_connects_the_chat_once_and_audits_it(
    t: Any, client_factory: Any, login: Any, sessions: Any
) -> None:
    owner = await _as(client_factory, login, "owner@t.ro")
    assert (await owner.get("/api/locations/test/telegram")).json() == {
        "connected": False,
        "chat_title": None,
    }
    code = await _link(owner)

    result = await _consume(sessions, code)
    assert (result.status, result.location_name) == ("linked", "Terasa")
    assert (await owner.get("/api/locations/test/telegram")).json() == {
        "connected": True,
        "chat_title": "Ospătari",
    }
    async with sessions() as s:
        site = await s.get(Site, "test")
        assert site is not None and site.telegram_chat_id == "-1001"
        entry = await s.scalar(
            select(AuditRow).where(AuditRow.kind == "location.telegram_connected")
        )
        assert entry is not None
        assert (entry.org_id, entry.location_id, entry.actor_id) == ("org-t", "test", "u-owner")
        assert entry.summary_ro == "Olga a conectat grupul Telegram „Ospătari” la Terasa"
        assert entry.after == {"telegram_chat_id": "-1001", "telegram_chat_title": "Ospătari"}
        assert code not in str(entry.before) + str(entry.after)

    # the same update redelivered: nothing changes, no reply; another chat: refused
    assert (await _consume(sessions, code)).status == "already_linked"
    assert (await _consume(sessions, code, chat="-1002", title="Alt grup")).status == "used"
    async with sessions() as s:
        site = await s.get(Site, "test")
        assert site is not None and site.telegram_chat_id == "-1001"
        kinds = list(await s.scalars(select(AuditRow.kind)))
        assert kinds.count("location.telegram_connected") == 1


async def test_expired_and_unknown_codes_change_nothing(
    t: Any, client_factory: Any, login: Any, sessions: Any
) -> None:
    owner = await _as(client_factory, login, "owner@t.ro")
    code = await _link(owner)
    async with sessions() as s:
        later = datetime.now(UTC) + timedelta(minutes=15, seconds=1)
        assert (await consume_link(s, code, "-1001", "Ospătari", now=later)).status == "expired"
    assert (await _consume(sessions, "nu-exista-acest-cod")).status == "unknown"
    assert (await _consume(sessions, "x" * 65)).status == "unknown"
    assert (await owner.get("/api/locations/test/telegram")).json()["connected"] is False
    # still valid before the expiry
    assert (await _consume(sessions, code)).status == "linked"


async def test_a_code_connects_only_its_own_location(
    t: Any, client_factory: Any, login: Any, sessions: Any
) -> None:
    owner = await _as(client_factory, login, "owner@t.ro")
    other_code = await _link(owner, "other")
    await _link(owner, "test")
    assert (await _consume(sessions, other_code)).location_name == "Sala mare"
    assert (await owner.get("/api/locations/other/telegram")).json()["connected"] is True
    assert (await owner.get("/api/locations/test/telegram")).json()["connected"] is False


async def test_a_manual_chat_id_drops_the_linked_title(
    t: Any, client_factory: Any, login: Any, sessions: Any
) -> None:
    owner = await _as(client_factory, login, "owner@t.ro")
    await _consume(sessions, await _link(owner))
    await owner.patch("/api/locations/test", json={"name": "Terasa"})
    status = (await owner.get("/api/locations/test/telegram")).json()
    assert status["chat_title"] == "Ospătari"  # an untouched chat keeps its title
    r = await owner.patch("/api/locations/test", json={"telegram_chat_id": "-1009"})
    assert r.status_code == 200 and r.json()["telegram_chat_id"] == "-1009"
    assert (await owner.get("/api/locations/test/telegram")).json() == {
        "connected": True,
        "chat_title": None,
    }
