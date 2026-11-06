"""Telegram Bot API notifier: sendPhoto with the blurred snapshot, else sendMessage.

The chat is the alert's location's `telegram_chat_id` (via `chat_for(event_id)`), else
TELEGRAM_CHAT_ID. Follow-ups (`send_text`) go to the same chat through the alert id tag.

The alert itself is HTML (`alert_message.render`) with an inline keyboard: "Preiau ✋"
(handled by the getUpdates poller, `telegram_ack.py`) and, when PUBLIC_DASHBOARD_URL is a
public https URL, "Vezi în aplicație". A 400 on that send (a caption, markup or button
Telegram refuses) is retried once as plain text without a keyboard: an alert is never lost.
"""

import html
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
from aivee_api.alerts.schemas import AlertView
from aivee_api.push.sender import PushKind
from aivee_contracts.events import AlertEvent

from aivee_ingest.alert_message import AlertContext, ack_line, basic_context, keyboard, render
from aivee_ingest.notify import with_prefix
from aivee_ingest.sent import SentMessage, SentMessages
from aivee_ingest.telegram_ack import event_of

log = logging.getLogger(__name__)

API = "https://api.telegram.org"

ChatLookup = Callable[[str], Awaitable[str | None]]
"""Alert (event) id → the location's chat id, or None."""
ContextLookup = Callable[[AlertEvent], Awaitable[AlertContext]]
"""Opened event → names for the message (location, camera, zone, rule, verification)."""


class TelegramNotifier:
    def __init__(
        self,
        token: str,
        chat_id: str | None,
        client: httpx.AsyncClient | None = None,
        prefix: str = "",
        *,
        chat_for: ChatLookup | None = None,
        context_for: ContextLookup | None = None,
        dashboard_url: str | None = None,
        sent: SentMessages | None = None,
    ) -> None:
        self._sent = sent
        self._base = f"{API}/bot{token}"
        self._chat_id = chat_id
        self._prefix = prefix
        self._client = client or httpx.AsyncClient(timeout=15)
        self._chat_for = chat_for
        self._context_for = context_for
        self._dashboard_url = dashboard_url

    async def _chat(self, event_id: str | None) -> str | None:
        own = await self._chat_for(event_id) if self._chat_for and event_id else None
        chat = own or self._chat_id
        if not chat:
            log.warning("no Telegram chat for alert %s (set it on the location)", event_id)
        return chat

    async def _context(self, event: AlertEvent) -> AlertContext:
        if self._context_for is not None:
            try:
                return await self._context_for(event)
            except Exception:
                log.exception("alert names for %s unavailable; sending ids", event.event_id)
        return basic_context(event)

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        chat_id = await self._chat(event.event_id)
        if not chat_id:
            return
        ctx = await self._context(event)
        text = render(ctx, prefix=self._prefix)
        markup = keyboard(event.event_id, self._dashboard_url)
        rich: dict[str, object] = {"chat_id": chat_id, "parse_mode": "HTML"}
        if markup is not None:
            rich["reply_markup"] = markup
        if snapshot is not None and snapshot.is_file():
            # Multipart: nested fields go as JSON strings.
            form = {k: v if isinstance(v, str) else json.dumps(v) for k, v in rich.items()}
            resp = await self._client.post(
                f"{self._base}/sendPhoto",
                data={**form, "caption": text},
                files={"photo": (snapshot.name, snapshot.read_bytes(), "image/jpeg")},
            )
        else:
            resp = await self._client.post(f"{self._base}/sendMessage", json={**rich, "text": text})
        if resp.status_code == 400:
            log.warning(
                "Telegram refused alert %s (%s); resending as plain text",
                event.event_id,
                resp.text[:200],
            )
            plain = render(ctx, prefix=self._prefix, as_html=False)
            resp = await self._client.post(
                f"{self._base}/sendMessage", json={"chat_id": chat_id, "text": plain}
            )
        self._check(resp)
        await self._remember(event.event_id, chat_id, resp)

    async def _remember(self, alert_id: str, chat_id: str, resp: httpx.Response) -> None:
        """Keep where the alert went, so it can be edited when it resolves."""
        if self._sent is None:
            return
        try:
            result = resp.json().get("result") or {}
            message_id = int(result["message_id"])
        except (ValueError, KeyError, TypeError, AttributeError):
            return
        try:
            await self._sent.save(alert_id, SentMessage(chat_id, message_id, "photo" in result))
        except Exception:
            log.exception("could not store the Telegram message of %s", alert_id)

    async def alert_resolved(self, view: AlertView, line: str) -> None:
        """Edit the original alert: `line` on top, the alert below, no buttons."""
        sent = await self._sent.get(view.event_id) if self._sent else None
        if sent is None:
            return
        ctx = await self._context(event_of(view))
        extra = (
            [ack_line(view.acknowledged_by, view.acknowledged_at)]
            if view.acknowledged_by and view.acknowledged_at
            else []
        )
        body = f"<b>{html.escape(line)}</b>\n\n" + render(ctx, prefix=self._prefix, extra=extra)
        payload: dict[str, Any] = {
            "chat_id": sent.chat_id,
            "message_id": sent.message_id,
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": []},
            ("caption" if sent.photo else "text"): body,
        }
        method = "editMessageCaption" if sent.photo else "editMessageText"
        resp = await self._client.post(f"{self._base}/{method}", json=payload)
        if resp.status_code == 400 and "not modified" in resp.text:
            return
        self._check(resp)

    async def alert_reminder(self, view: AlertView, text: str) -> None:
        """A short reply to the original alert, with the same buttons."""
        sent = await self._sent.get(view.event_id) if self._sent else None
        chat_id = sent.chat_id if sent else await self._chat(view.event_id)
        if not chat_id:
            return
        payload: dict[str, Any] = {"chat_id": chat_id, "text": with_prefix(self._prefix, text)}
        markup = keyboard(view.event_id, self._dashboard_url)
        if markup is not None:
            payload["reply_markup"] = markup
        if sent is not None:
            payload["reply_parameters"] = {
                "message_id": sent.message_id,
                "allow_sending_without_reply": True,
            }
        resp = await self._client.post(f"{self._base}/sendMessage", json=payload)
        self._check(resp)

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None, kind: PushKind
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
