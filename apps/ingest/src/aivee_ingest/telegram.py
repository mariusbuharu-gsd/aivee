"""Telegram Bot API notifier: sendPhoto with the blurred snapshot, else sendMessage."""

from pathlib import Path

import httpx
from aivee_contracts.events import AlertEvent

from aivee_ingest.notify import alert_text, with_prefix

API = "https://api.telegram.org"


class TelegramNotifier:
    def __init__(
        self,
        token: str,
        chat_id: str,
        client: httpx.AsyncClient | None = None,
        prefix: str = "",
    ) -> None:
        self._base = f"{API}/bot{token}"
        self._chat_id = chat_id
        self._prefix = prefix
        self._client = client or httpx.AsyncClient(timeout=15)

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        text = alert_text(event, self._prefix)
        if snapshot is not None and snapshot.is_file():
            resp = await self._client.post(
                f"{self._base}/sendPhoto",
                data={"chat_id": self._chat_id, "caption": text},
                files={"photo": (snapshot.name, snapshot.read_bytes(), "image/jpeg")},
            )
        else:
            resp = await self._client.post(
                f"{self._base}/sendMessage", json={"chat_id": self._chat_id, "text": text}
            )
        self._check(resp)

    async def send_text(self, text: str, tag: str | None = None) -> None:
        resp = await self._client.post(
            f"{self._base}/sendMessage",
            json={"chat_id": self._chat_id, "text": with_prefix(self._prefix, text)},
        )
        self._check(resp)

    @staticmethod
    def _check(resp: httpx.Response) -> None:
        if resp.is_error:
            # Never include the request URL: it carries the bot token.
            raise RuntimeError(f"Telegram API error {resp.status_code}: {resp.text[:200]}")

    async def aclose(self) -> None:
        await self._client.aclose()
