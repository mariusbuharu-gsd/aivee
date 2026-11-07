"""The bot side of "Conectează Telegram": a getUpdates long-polling loop.

The dashboard opens `t.me/<bot>?startgroup=<code>`; Telegram adds the bot to the chosen group
and posts `/start@<bot> <code>` there (`/start <code>` in a private chat). The poller resolves
the code (`aivee_api.locations.telegram.consume_link`), which saves the chat on the location,
and replies in that chat. `my_chat_member` updates carry no payload, so the code always comes
from the message. `callback_query` updates (the alert's "Preiau ✋" button) go to
`telegram_ack.AlertCallbacks`.

Exactly one process may call getUpdates for a bot token: a second caller (or a webhook) gets
HTTP 409. Every ingest replica runs this loop, but only the one holding the Postgres advisory
lock `POLL_LOCK_KEY` polls; the others wait and take over when it goes away. TELEGRAM_POLL=false
turns the loop off on an instance. A 409 (webhook set, or a poller outside this stack such as
`make telegram-id`) is logged and retried after a back-off; it never stops the notifier.
"""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx
from aivee_api.locations.telegram import LinkResult, consume_link
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from aivee_ingest.telegram import API
from aivee_ingest.telegram_ack import AlertCallbacks

log = logging.getLogger(__name__)

POLL_LOCK_KEY = 0x41495645_7467  # "AIVE" "tg": one getUpdates poller per database
START = re.compile(r"^/start(?:@(?P<bot>\w+))?(?:\s+(?P<code>\S+))?\s*$")

LINKED = "✅ AiVee e conectat la «{location}». Aici vor veni alertele."
EXPIRED = (
    "Linkul de conectare a expirat (e valabil 15 minute). "
    "Cere unul nou din AiVee: Locații → Conectează Telegram."
)
USED = (
    "Acest link a fost deja folosit. "
    "Dacă vrei alertele aici, cere unul nou din AiVee: Locații → Conectează Telegram."
)
UNKNOWN = "Nu recunosc acest cod. Cere un link nou din AiVee: Locații → Conectează Telegram."
HELLO = (
    "Salut! Sunt botul AiVee. Ca să primești alertele unei locații, deschide AiVee: "
    "Locații → Conectează Telegram."
)
REPLIES = {"linked": LINKED, "expired": EXPIRED, "used": USED, "unknown": UNKNOWN}

Update = dict[str, Any]

ALLOWED_UPDATES = ["message", "my_chat_member", "callback_query"]
"""Sent on every getUpdates: Telegram remembers the last list, so be explicit."""


class PollConflict(Exception):
    """getUpdates answered 409: a webhook is set or another process polls this bot."""


class BotApi(Protocol):
    async def get_updates(self, offset: int | None, timeout_s: int) -> list[Update]: ...

    async def send_message(self, chat_id: str, text: str) -> None: ...

    async def username(self) -> str | None: ...


class LinkStore(Protocol):
    async def consume(self, code: str, chat_id: str, chat_title: str | None) -> LinkResult: ...


class PollLock(Protocol):
    async def acquire(self) -> bool:
        """True while this process may poll (taking the lock if free)."""
        ...

    async def release(self) -> None: ...


class HttpBotApi:
    """Bot API over httpx. Errors never include the request URL (it carries the token)."""

    def __init__(self, token: str, client: httpx.AsyncClient | None = None) -> None:
        self._base = f"{API}/bot{token}"
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(10, read=40))
        self._username: str | None = None

    async def _call(self, method: str, payload: dict[str, Any]) -> Any:
        resp = await self._client.post(f"{self._base}/{method}", json=payload)
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code == 409:
            raise PollConflict(str(body.get("description", ""))[:200])
        if resp.is_error or not body.get("ok"):
            raise RuntimeError(
                f"Telegram {method} {resp.status_code}: {str(body.get('description', ''))[:200]}"
            )
        return body.get("result")

    async def get_updates(self, offset: int | None, timeout_s: int) -> list[Update]:
        payload: dict[str, Any] = {"timeout": timeout_s, "allowed_updates": ALLOWED_UPDATES}
        if offset is not None:
            payload["offset"] = offset
        result = await self._call("getUpdates", payload)
        return list(result or [])

    async def send_message(self, chat_id: str, text: str) -> None:
        await self._call("sendMessage", {"chat_id": chat_id, "text": text})

    async def answer_callback(self, query_id: str, text: str) -> None:
        await self._call("answerCallbackQuery", {"callback_query_id": query_id, "text": text})

    async def edit_message(self, method: str, payload: dict[str, Any]) -> None:
        await self._call(method, payload)

    async def username(self) -> str | None:
        if self._username is None:
            me = await self._call("getMe", {})
            self._username = me.get("username") if isinstance(me, dict) else None
        return self._username

    async def aclose(self) -> None:
        await self._client.aclose()


class DbLinkStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def consume(self, code: str, chat_id: str, chat_title: str | None) -> LinkResult:
        async with self._sessions() as s:
            return await consume_link(s, code, chat_id, chat_title)


class AdvisoryPollLock:
    """A session-level `pg_try_advisory_lock` held on one dedicated connection.

    The lock lives as long as that connection: if the process or its connection dies,
    Postgres releases it and another replica takes over on its next try. Every `acquire`
    asks Postgres again on the same connection (the lock is re-entrant), so a connection
    that silently reconnected never counts as still holding it."""

    def __init__(self, engine: AsyncEngine, key: int = POLL_LOCK_KEY) -> None:
        self._engine = engine
        self._key = key
        self._conn: AsyncConnection | None = None

    async def acquire(self) -> bool:
        conn = self._conn or await self._engine.connect()
        try:
            got = bool(await conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": self._key}))
            await conn.commit()
        except Exception:
            self._conn = None
            await conn.invalidate()  # never hand a connection that may hold the lock back
            await conn.close()
            raise
        if got:
            self._conn = conn
        else:
            if self._conn is not None:
                log.info("Telegram poll lock lost")
            self._conn = None
            await conn.close()  # holds nothing: try-lock failed on it
        return got

    async def release(self) -> None:
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            await conn.execute(text("SELECT pg_advisory_unlock_all()"))
            await conn.commit()
        except Exception:
            log.warning("could not release the Telegram poll lock; dropping its connection")
            await conn.invalidate()
        await conn.close()


def _safe(e: Exception) -> str:
    """httpx errors may carry the request URL, and with it the token: name them only."""
    return type(e).__name__ if isinstance(e, httpx.HTTPError) else str(e) or type(e).__name__


def _chat_title(chat: dict[str, Any]) -> str | None:
    title = chat.get("title")
    if title:
        return str(title)
    name = " ".join(str(chat[k]) for k in ("first_name", "last_name") if chat.get(k))
    return name or (f"@{chat['username']}" if chat.get("username") else None)


class TelegramLinkBot:
    """Handles one update: `/start <code>` links the chat to the code's location."""

    def __init__(
        self, api: BotApi, store: LinkStore, callbacks: AlertCallbacks | None = None
    ) -> None:
        self._api = api
        self._store = store
        self._callbacks = callbacks

    async def handle(self, update: Update) -> None:
        query = update.get("callback_query")
        if isinstance(query, dict):
            if self._callbacks is not None:
                await self._callbacks.handle(query)
            return
        message = update.get("message")
        if not isinstance(message, dict):
            return  # my_chat_member and the rest carry no start payload
        match = START.match(str(message.get("text") or ""))
        chat = message.get("chat") or {}
        if match is None or "id" not in chat:
            return
        addressed = match.group("bot")
        if addressed:
            try:
                mine = await self._api.username()
            except Exception as e:
                log.warning("Telegram getMe failed: %s", _safe(e))
                mine = None
            if mine and addressed.lower() != mine.lower():
                return  # /start@another_bot in a shared group
        chat_id = str(chat["id"])
        code = match.group("code")
        if not code:
            if chat.get("type") == "private":
                await self._reply(chat_id, HELLO)
            return
        result = await self._store.consume(code, chat_id, _chat_title(chat))
        log.info("Telegram link code in chat %s: %s", chat_id, result.status)
        template = REPLIES.get(result.status)
        if template is not None:  # already_linked: a redelivered update, stay quiet
            await self._reply(chat_id, template.format(location=result.location_name or ""))

    async def _reply(self, chat_id: str, text: str) -> None:
        try:
            await self._api.send_message(chat_id, text)
        except Exception as e:
            log.warning("Telegram reply to %s failed: %s", chat_id, _safe(e))


Sleep = Callable[[float], Awaitable[None]]


async def run_link_poller(
    bot: TelegramLinkBot,
    api: BotApi,
    lock: PollLock,
    *,
    timeout_s: int = 25,
    standby_s: float = 30,
    conflict_s: float = 60,
    error_s: float = 5,
    sleep: Sleep = asyncio.sleep,
    cycles: int | None = None,
) -> None:
    """Poll forever (or `cycles` times, for tests). Never raises except on cancel."""
    offset: int | None = None
    leader = False
    done = 0
    try:
        while cycles is None or done < cycles:
            done += 1
            try:
                if not await lock.acquire():
                    if leader:
                        log.info("Telegram poll lock lost; another replica polls")
                    leader = False
                    await sleep(standby_s)
                    continue
                if not leader:
                    log.info("this replica polls Telegram for link codes")
                    leader = True
                updates = await api.get_updates(offset, timeout_s)
            except PollConflict as e:
                log.warning(
                    "Telegram getUpdates conflict (a webhook is set or another poller runs): "
                    "%s; retrying in %.0f s",
                    e,
                    conflict_s,
                )
                await sleep(conflict_s)
                continue
            except Exception as e:
                log.warning("Telegram poll failed: %s; retrying in %.0f s", _safe(e), error_s)
                await sleep(error_s)
                continue
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = max(offset or 0, update_id + 1)
                try:
                    await bot.handle(update)
                except Exception:
                    log.exception("Telegram update %s failed", update_id)
    finally:
        await lock.release()
