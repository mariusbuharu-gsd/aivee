"""The "Preiau ✋" button: a `callback_query` acknowledges the alert from Telegram.

The getUpdates poller (`telegram_link.py`, one replica) hands every callback here. The ack
goes through `AlertRepository.acknowledge`, the dashboard's "Merg eu" path, with the
Telegram user's first name as `acknowledged_by` (no AiVee account: `acknowledged_by_id`
stays empty), plus an `alert.acknowledged` audit entry. Only the chat the alert was sent to
(the location's chat, else TELEGRAM_CHAT_ID) may take it. The dashboard picks the ack up
like any other (`acknowledged_after`).

Every callback is answered (a toast), or the button keeps spinning. After an ack the
message gets "✋ Preluată de Ana · 16:58" and loses the button; already taken or closed
alerts only lose the button.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from aivee_api.alerts.audit import AuditWriter, acknowledged_entry
from aivee_api.alerts.auth import AlertUser
from aivee_api.alerts.repository import AlertRepository
from aivee_api.alerts.schemas import AlertView
from aivee_api.db.models import Site
from aivee_contracts.events import AlertEvent
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_ingest.alert_message import AlertContext, ack_line, alert_ref, keyboard, render
from aivee_ingest.locations import alert_context

log = logging.getLogger(__name__)

TAKEN = "Preluată ✓"
ALREADY = "Deja preluată de {who}"
CLOSED = "Alerta s-a închis"
WRONG_CHAT = "Alerta nu e pentru acest grup."
UNKNOWN = "Nu mai găsesc alerta."
FAILED = "Nu am putut prelua alerta. Încearcă din aplicație."

AckStatus = Literal["acked", "already", "closed", "wrong_chat", "unknown"]


@dataclass(frozen=True)
class AckOutcome:
    status: AckStatus
    by: str | None = None
    at: datetime | None = None
    context: AlertContext | None = None
    """The alert's message context, to re-render it after an ack."""


class AckStore(Protocol):
    async def acknowledge(
        self, ref: str, chat_id: str, name: str, telegram_user_id: str
    ) -> AckOutcome: ...


class CallbackApi(Protocol):
    async def answer_callback(self, query_id: str, text: str) -> None: ...

    async def edit_message(self, method: str, payload: dict[str, Any]) -> None:
        """editMessageText / editMessageCaption / editMessageReplyMarkup."""
        ...


def _now() -> datetime:
    return datetime.now(UTC)


def _event_of(view: AlertView) -> AlertEvent:
    return AlertEvent(
        event_id=view.event_id,
        rule_id=view.rule_id,
        camera_id=view.camera_id,
        zone_id=view.zone_id,
        state="opened",
        at=view.opened_at,
        summary_ro=view.summary_ro,
        snapshot=view.snapshot,
    )


class DbAckStore:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        audit: AuditWriter,
        default_chat_id: str | None = None,
        now: Callable[[], datetime] = _now,
    ) -> None:
        self._sessions = sessions
        self._audit = audit
        self._default_chat = default_chat_id
        self._now = now

    async def acknowledge(
        self, ref: str, chat_id: str, name: str, telegram_user_id: str
    ) -> AckOutcome:
        async with self._sessions() as s:
            repo = AlertRepository(s)
            alert_id = await repo.resolve(ref)
            view = await repo.view(alert_id) if alert_id else None
            if alert_id is None or view is None:
                return AckOutcome("unknown")
            site = await s.get(Site, view.location_id) if view.location_id else None
            expected = (site.telegram_chat_id if site else None) or self._default_chat
            if not expected or str(expected) != chat_id:
                return AckOutcome("wrong_chat")
            at = self._now()
            # The holder of the id is not an AiVee user: the name is the whole record.
            if not await repo.acknowledge(alert_id, AlertUser("", name), at):
                if view.closed_at is not None:
                    return AckOutcome("closed")
                if view.acknowledged_at is None:  # lost a race: read who won
                    view = await repo.view(alert_id) or view
                    if view.closed_at is not None:
                        return AckOutcome("closed")
                return AckOutcome("already", by=view.acknowledged_by)
            acked = await repo.view(alert_id)
            assert acked is not None
            entry = acknowledged_entry(acked, AlertUser(f"telegram:{telegram_user_id}", name))
            await self._audit.append(s, replace(entry, after={"via": "telegram"}))
            await s.commit()
        context = await alert_context(self._sessions, _event_of(acked))
        return AckOutcome("acked", by=name, at=at, context=context)


def _first_name(user: dict[str, Any]) -> str:
    name = user.get("first_name") or user.get("username")
    return str(name).strip() if name else "Cineva"


class AlertCallbacks:
    def __init__(
        self,
        api: CallbackApi,
        store: AckStore,
        *,
        prefix: str = "",
        dashboard_url: str | None = None,
    ) -> None:
        self._api = api
        self._store = store
        self._prefix = prefix
        self._dashboard_url = dashboard_url

    async def handle(self, query: dict[str, Any]) -> None:
        query_id = str(query.get("id", ""))
        message = query.get("message") if isinstance(query.get("message"), dict) else None
        chat = (message or {}).get("chat") or {}
        ref = alert_ref(query.get("data"))
        if ref is None or message is None or "id" not in chat:
            await self._answer(query_id, UNKNOWN)
            return
        user = query.get("from") or {}
        name = _first_name(user)
        try:
            outcome = await self._store.acknowledge(
                ref, str(chat["id"]), name, str(user.get("id", ""))
            )
        except Exception:
            log.exception("Telegram ack of %s failed", ref)
            await self._answer(query_id, FAILED)
            return
        log.info("Telegram ack of %s by %s: %s", ref, name, outcome.status)
        match outcome.status:
            case "acked":
                await self._answer(query_id, TAKEN)
                await self._mark_taken(message, ref, outcome)
            case "already":
                await self._answer(query_id, ALREADY.format(who=outcome.by or "altcineva"))
                await self._drop_button(message, ref)
            case "closed":
                await self._answer(query_id, CLOSED)
                await self._drop_button(message, ref)
            case "wrong_chat":
                await self._answer(query_id, WRONG_CHAT)
            case _:
                await self._answer(query_id, UNKNOWN)

    def _markup(self, ref: str) -> dict[str, Any]:
        return keyboard(ref, self._dashboard_url, with_ack=False) or {"inline_keyboard": []}

    async def _mark_taken(self, message: dict[str, Any], ref: str, outcome: AckOutcome) -> None:
        if outcome.context is None or outcome.at is None:
            await self._drop_button(message, ref)
            return
        body = render(
            outcome.context,
            prefix=self._prefix,
            extra=[ack_line(outcome.by or "Cineva", outcome.at)],
        )
        photo = "photo" in message
        payload: dict[str, Any] = {
            "chat_id": message["chat"]["id"],
            "message_id": message.get("message_id"),
            "parse_mode": "HTML",
            "reply_markup": self._markup(ref),
            ("caption" if photo else "text"): body,
        }
        try:
            await self._api.edit_message(
                "editMessageCaption" if photo else "editMessageText", payload
            )
        except Exception as e:
            log.warning("could not edit the Telegram alert %s: %s", ref, type(e).__name__)
            await self._drop_button(message, ref)

    async def _drop_button(self, message: dict[str, Any], ref: str) -> None:
        payload = {
            "chat_id": message["chat"]["id"],
            "message_id": message.get("message_id"),
            "reply_markup": self._markup(ref),
        }
        try:
            await self._api.edit_message("editMessageReplyMarkup", payload)
        except Exception as e:
            log.warning("could not remove the Telegram button of %s: %s", ref, type(e).__name__)

    async def _answer(self, query_id: str, text: str) -> None:
        if not query_id:
            return
        try:
            await self._api.answer_callback(query_id, text)
        except Exception as e:
            log.warning("Telegram answerCallbackQuery failed: %s", type(e).__name__)
