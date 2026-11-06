"""The "Conectează Telegram" bot: update handling and the polling loop, with fakes only."""

import json
from typing import Any

import httpx
import pytest
from aivee_api.locations.telegram import LinkResult
from aivee_ingest.telegram_link import (
    EXPIRED,
    HELLO,
    UNKNOWN,
    USED,
    HttpBotApi,
    PollConflict,
    TelegramLinkBot,
    run_link_poller,
)

GROUP = {"id": -1001234, "type": "supergroup", "title": "Ospătari Terasa"}
PRIVATE = {"id": 42, "type": "private", "first_name": "Olga", "last_name": "Pop"}


class FakeApi:
    def __init__(self, batches: list[Any] | None = None, username: str | None = "aivee_bot"):
        self.batches = list(batches or [])
        self.offsets: list[int | None] = []
        self.sent: list[tuple[str, str]] = []
        self._username = username

    async def get_updates(self, offset: int | None, timeout_s: int) -> list[dict[str, Any]]:
        self.offsets.append(offset)
        batch = self.batches.pop(0) if self.batches else []
        if isinstance(batch, Exception):
            raise batch
        return list(batch)

    async def send_message(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))

    async def username(self) -> str | None:
        return self._username


class FakeStore:
    """Code "good" → Terasa (single use), "old" expired, anything else unknown."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []
        self.linked: dict[str, str] = {}

    async def consume(self, code: str, chat_id: str, chat_title: str | None) -> LinkResult:
        self.calls.append((code, chat_id, chat_title))
        if code == "good":
            if "good" in self.linked:
                same = self.linked["good"] == chat_id
                return LinkResult("already_linked" if same else "used", "Terasa")
            self.linked["good"] = chat_id
            return LinkResult("linked", "Terasa")
        if code == "old":
            return LinkResult("expired", "Terasa")
        return LinkResult("unknown")


class FakeLock:
    def __init__(self, answers: list[bool] | None = None) -> None:
        self.answers = list(answers or [])
        self.released = 0

    async def acquire(self) -> bool:
        return self.answers.pop(0) if self.answers else True

    async def release(self) -> None:
        self.released += 1


def _msg(text: str, chat: dict[str, Any], update_id: int = 1) -> dict[str, Any]:
    return {"update_id": update_id, "message": {"message_id": 7, "chat": chat, "text": text}}


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def bot(api: FakeApi, store: FakeStore) -> TelegramLinkBot:
    return TelegramLinkBot(api, store)


async def test_group_start_links_the_group(
    bot: TelegramLinkBot, api: FakeApi, store: FakeStore
) -> None:
    await bot.handle(_msg("/start@aivee_bot good", GROUP))
    assert store.calls == [("good", "-1001234", "Ospătari Terasa")]
    assert api.sent == [("-1001234", "✅ AiVee e conectat la «Terasa». Aici vor veni alertele.")]


async def test_private_start_links_the_private_chat(
    bot: TelegramLinkBot, api: FakeApi, store: FakeStore
) -> None:
    await bot.handle(_msg("/start good", PRIVATE))
    assert store.calls == [("good", "42", "Olga Pop")]
    assert api.sent[0][0] == "42" and "«Terasa»" in api.sent[0][1]


async def test_expired_and_unknown_codes_get_a_polite_reply(
    bot: TelegramLinkBot, api: FakeApi
) -> None:
    await bot.handle(_msg("/start old", GROUP))
    await bot.handle(_msg("/start nimic-nimic", GROUP))
    assert api.sent == [("-1001234", EXPIRED), ("-1001234", UNKNOWN)]


async def test_reused_code(bot: TelegramLinkBot, api: FakeApi, store: FakeStore) -> None:
    await bot.handle(_msg("/start good", GROUP))
    await bot.handle(_msg("/start good", GROUP))  # redelivered: quiet
    await bot.handle(_msg("/start good", PRIVATE))  # another chat: refused
    assert [text for _, text in api.sent][1:] == [USED]
    assert store.linked == {"good": "-1001234"}


async def test_ignores_what_is_not_a_start_for_this_bot(
    bot: TelegramLinkBot, api: FakeApi, store: FakeStore
) -> None:
    await bot.handle(_msg("/start@other_bot good", GROUP))
    await bot.handle(_msg("salut good", GROUP))
    await bot.handle(_msg("/start", GROUP))
    await bot.handle({"update_id": 3, "my_chat_member": {"chat": GROUP}})
    await bot.handle({"update_id": 4, "message": {"chat": GROUP}})  # a photo, no text
    assert store.calls == [] and api.sent == []


async def test_bare_start_in_private_explains(bot: TelegramLinkBot, api: FakeApi) -> None:
    await bot.handle(_msg("/start", PRIVATE))
    assert api.sent == [("42", HELLO)]


async def test_bot_name_is_case_insensitive(store: FakeStore) -> None:
    bot = TelegramLinkBot(FakeApi(username="AiVeeBot"), store)
    await bot.handle(_msg("/start@aiveebot good", GROUP))
    assert store.calls


async def _no_sleep(_: float) -> None:
    return None


async def test_poller_advances_the_offset_and_survives_a_bad_update(
    api: FakeApi, store: FakeStore
) -> None:
    class Flaky(TelegramLinkBot):
        async def handle(self, update: dict[str, Any]) -> None:
            if update["update_id"] == 10:
                raise ValueError("boom")
            await super().handle(update)

    api.batches = [[{"update_id": 10}, _msg("/start good", GROUP, 11)], []]
    lock = FakeLock()
    await run_link_poller(Flaky(api, store), api, lock, sleep=_no_sleep, cycles=2)
    assert api.offsets == [None, 12]
    assert store.linked == {"good": "-1001234"}
    assert lock.released == 1


async def test_poller_backs_off_on_conflict_and_errors(api: FakeApi, bot: TelegramLinkBot) -> None:
    api.batches = [PollConflict("webhook is active"), RuntimeError("Telegram 502"), []]
    slept: list[float] = []

    async def sleep(s: float) -> None:
        slept.append(s)

    await run_link_poller(bot, api, FakeLock(), sleep=sleep, conflict_s=60, error_s=5, cycles=3)
    assert slept == [60, 5]
    assert len(api.offsets) == 3


async def test_only_the_lock_holder_polls(api: FakeApi, bot: TelegramLinkBot) -> None:
    slept: list[float] = []

    async def sleep(s: float) -> None:
        slept.append(s)

    lock = FakeLock([False, False, True])
    await run_link_poller(bot, api, lock, sleep=sleep, standby_s=30, cycles=3)
    assert slept == [30, 30]
    assert api.offsets == [None]  # polled once, after taking the lock
    assert lock.released == 1


def _http(status: int, body: dict[str, Any]) -> tuple[HttpBotApi, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    return HttpBotApi("SECRET", httpx.AsyncClient(transport=httpx.MockTransport(handler))), seen


async def test_http_get_updates_sends_offset_and_timeout() -> None:
    api, seen = _http(200, {"ok": True, "result": [{"update_id": 5}]})
    assert await api.get_updates(5, 25) == [{"update_id": 5}]
    assert seen[0].url.path == "/botSECRET/getUpdates"
    assert json.loads(seen[0].content) == {"offset": 5, "timeout": 25}


async def test_http_409_is_a_conflict_without_the_token() -> None:
    desc = "Conflict: can't use getUpdates method while webhook is active"
    api, _ = _http(409, {"ok": False, "error_code": 409, "description": desc})
    with pytest.raises(PollConflict) as err:
        await api.get_updates(None, 25)
    assert "webhook" in str(err.value) and "SECRET" not in str(err.value)


async def test_http_error_never_shows_the_token() -> None:
    api, _ = _http(401, {"ok": False, "description": "Unauthorized"})
    with pytest.raises(RuntimeError) as err:
        await api.send_message("-1", "x")
    assert "SECRET" not in str(err.value) and "401" in str(err.value)


async def test_http_username_is_cached() -> None:
    api, seen = _http(200, {"ok": True, "result": {"username": "aivee_bot"}})
    assert await api.username() == "aivee_bot"
    assert await api.username() == "aivee_bot"
    assert len(seen) == 1
