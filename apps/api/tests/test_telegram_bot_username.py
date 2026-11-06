"""The bot's @username for deep links: config first, else getMe once (faked here)."""

import httpx
from aivee_api.locations.telegram import TelegramBotUsername


def _client(status: int = 200, username: str = "aivee_bot") -> tuple[httpx.AsyncClient, list[str]]:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(status, json={"ok": status == 200, "result": {"username": username}})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), paths


async def test_configured_username_needs_no_call() -> None:
    client, paths = _client()
    bot = TelegramBotUsername("@aivee_cfg_bot", "TOKEN", client)
    assert await bot.username() == "aivee_cfg_bot"
    assert paths == []


async def test_get_me_once_then_cached() -> None:
    client, paths = _client()
    bot = TelegramBotUsername(None, "TOKEN", client)
    assert await bot.username() == "aivee_bot"
    assert await bot.username() == "aivee_bot"
    assert paths == ["/botTOKEN/getMe"]


async def test_failed_get_me_is_retried_later() -> None:
    client, paths = _client(status=401)
    bot = TelegramBotUsername(None, "TOKEN", client)
    assert await bot.username() is None
    assert await bot.username() is None
    assert len(paths) == 2


async def test_no_token_no_username() -> None:
    assert await TelegramBotUsername(None, None).username() is None
