"""Telegram Bot API notifier: sendPhoto with the blurred snapshot, else sendMessage.

The chat is the alert's location's `telegram_chat_id` (via `chat_for(event_id)`), else
TELEGRAM_CHAT_ID. Follow-ups (`send_text`) go to the same chat through the alert id tag.
"""

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from aivee_contracts.events import AlertEvent

from aivee_ingest.notify import alert_text, with_prefix

log = logging.getLogger(__name__)

API = "https://api.telegram.org"

ChatLookup = Callable[[str], Awaitable[str | None]]
"""Alert (event) id → the location's chat id, or None."""


class TelegramNotifier:
    def __init__(
        self,
        token: str,
        chat_id: str | None,
        client: httpx.AsyncClient | None = None,
        prefix: str = "",
        *,
        chat_for: ChatLookup | None = None,
    ) -> None:
        self._base = f"{API}/bot{token}"
        self._chat_id = chat_id
        self._prefix = prefix
        self._client = client or httpx.AsyncClient(timeout=15)
        self._chat_for = chat_for

    async def _chat(self, event_id: str | None) -> str | None:
        own = await self._chat_for(event_id) if self._chat_for and event_id else None
        chat = own or self._chat_id
        if not chat:
            log.warning("no Telegram chat for alert %s (set it on the location)", event_id)
        return chat

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        chat_id = await self._chat(event.event_id)
        if not chat_id:
            return
        text = alert_text(event, self._prefix)
        if snapshot is not None and snapshot.is_file():
            resp = await self._client.post(
                f"{self._base}/sendPhoto",
                data={"chat_id": chat_id, "caption": text},
                files={"photo": (snapshot.name, snapshot.read_bytes(), "image/jpeg")},
            )
        else:
            resp = await self._client.post(
                f"{self._base}/sendMessage", json={"chat_id": chat_id, "text": text}
            )
        self._check(resp)

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None
    ) -> None:
        chat_id = await self._chat(tag)
        if not chat_id:
            return
        resp = await self._client.post(
            f"{self._base}/sendMessage",
            json={"chat_id": chat_id, "text": with_prefix(self._prefix, text)},
        )
        self._check(resp)

    @staticmethod
    def _check(resp: httpx.Response) -> None:
        if resp.is_error:
            # Never include the request URL: it carries the bot token.
            raise RuntimeError(f"Telegram API error {resp.status_code}: {resp.text[:200]}")

    async def aclose(self) -> None:
        await self._client.aclose()
