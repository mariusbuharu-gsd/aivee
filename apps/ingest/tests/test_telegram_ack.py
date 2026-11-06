"""The "Preiau ✋" button: callback_query handling with fake updates, a fake store and API."""

from datetime import UTC, datetime
from typing import Any

from aivee_contracts.events import AlertEvent
from aivee_contracts.rules import Condition
from aivee_ingest.alert_message import AlertContext
from aivee_ingest.telegram_ack import AckOutcome, AlertCallbacks
from aivee_ingest.telegram_link import TelegramLinkBot

CHAT = -1001234
ALERT = "3f2c1e0a-0000-4000-8000-000000000001"
AT = datetime(2026, 11, 6, 14, 56, tzinfo=UTC)
TAKEN_AT = datetime(2026, 11, 6, 14, 58, tzinfo=UTC)  # 16:58 in Bucharest
CTX = AlertContext(
    AlertEvent(
        event_id=ALERT,
        rule_id="r1",
        camera_id="cam-01",
        zone_id="z1",
        state="opened",
        at=AT,
        summary_ro="Masa 1: neservită de 1 min",
    ),
    zone_name="Masa 1",
    location_name="Terasa demo",
    camera_name="Sala principală",
    conditions=[Condition(kind="absent", role="staff", min_duration_s=60)],
)


class FakeApi:
    def __init__(self) -> None:
        self.answers: list[tuple[str, str]] = []
        self.edits: list[tuple[str, dict[str, Any]]] = []
        self.fail_edits = False

    async def answer_callback(self, query_id: str, text: str) -> None:
        self.answers.append((query_id, text))

    async def edit_message(self, method: str, payload: dict[str, Any]) -> None:
        self.edits.append((method, payload))
        if self.fail_edits and method != "editMessageReplyMarkup":
            raise RuntimeError("Telegram editMessageCaption 400")


class FakeStore:
    def __init__(self, outcome: AckOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, str, str, str]] = []

    async def acknowledge(
        self, ref: str, chat_id: str, name: str, telegram_user_id: str
    ) -> AckOutcome:
        self.calls.append((ref, chat_id, name, telegram_user_id))
        return self.outcome


def _query(data: str = f"ack:{ALERT}", *, photo: bool = True, chat: int = CHAT) -> dict[str, Any]:
    message: dict[str, Any] = {"message_id": 77, "chat": {"id": chat, "type": "supergroup"}}
    if photo:
        message["photo"] = [{"file_id": "x"}]
        message["caption"] = "🔴 Masa 1 așteaptă de 1 min"
    else:
        message["text"] = "🔴 Masa 1 așteaptă de 1 min"
    return {
        "id": "q1",
        "from": {"id": 555, "first_name": "Ana", "last_name": "Pop"},
        "message": message,
        "data": data,
    }


def _bot(
    outcome: AckOutcome, dashboard: str | None = None
) -> tuple[AlertCallbacks, FakeApi, FakeStore]:
    api, store = FakeApi(), FakeStore(outcome)
    return AlertCallbacks(api, store, dashboard_url=dashboard), api, store


async def test_ack_answers_edits_the_caption_and_drops_the_button() -> None:
    callbacks, api, store = _bot(AckOutcome("acked", by="Ana", at=TAKEN_AT, context=CTX))
    await callbacks.handle(_query())
    assert store.calls == [(ALERT, str(CHAT), "Ana", "555")]
    assert api.answers == [("q1", "Preluată ✓")]
    [(method, payload)] = api.edits
    assert method == "editMessageCaption"
    assert payload["chat_id"] == CHAT and payload["message_id"] == 77
    assert payload["parse_mode"] == "HTML"
    assert payload["caption"] == (
        "🔴 <b>Masa 1 așteaptă de 1 min</b>\nNu a venit nimeni la client.\n\n"
        "📍 Terasa demo · Sala principală · 16:56\n✋ Preluată de Ana · 16:58"
    )
    assert payload["reply_markup"] == {"inline_keyboard": []}


async def test_ack_of_a_text_message_edits_the_text_and_keeps_the_dashboard_link() -> None:
    callbacks, api, _ = _bot(
        AckOutcome("acked", by="Ana", at=TAKEN_AT, context=CTX), "https://aivee.example.com"
    )
    await callbacks.handle(_query(photo=False))
    [(method, payload)] = api.edits
    assert method == "editMessageText"
    assert payload["text"].endswith("✋ Preluată de Ana · 16:58")
    assert payload["reply_markup"] == {
        "inline_keyboard": [
            [{"text": "Vezi în aplicație", "url": "https://aivee.example.com/alerte"}]
        ]
    }


async def test_a_refused_edit_still_removes_the_button() -> None:
    callbacks, api, _ = _bot(AckOutcome("acked", by="Ana", at=TAKEN_AT, context=CTX))
    api.fail_edits = True
    await callbacks.handle(_query())
    assert [m for m, _ in api.edits] == ["editMessageCaption", "editMessageReplyMarkup"]
    assert api.answers == [("q1", "Preluată ✓")]


async def test_already_taken_says_by_whom_and_drops_the_button() -> None:
    callbacks, api, _ = _bot(AckOutcome("already", by="Mihai"))
    await callbacks.handle(_query())
    assert api.answers == [("q1", "Deja preluată de Mihai")]
    assert api.edits == [
        (
            "editMessageReplyMarkup",
            {"chat_id": CHAT, "message_id": 77, "reply_markup": {"inline_keyboard": []}},
        )
    ]


async def test_closed_alert_says_so_and_drops_the_button() -> None:
    callbacks, api, _ = _bot(AckOutcome("closed"))
    await callbacks.handle(_query())
    assert api.answers == [("q1", "Alerta s-a închis")]
    assert [m for m, _ in api.edits] == ["editMessageReplyMarkup"]


async def test_wrong_chat_is_refused_without_touching_the_message() -> None:
    callbacks, api, _ = _bot(AckOutcome("wrong_chat"))
    await callbacks.handle(_query(chat=-999))
    assert api.answers == [("q1", "Alerta nu e pentru acest grup.")]
    assert api.edits == []


async def test_unknown_alert_and_foreign_data_get_a_toast_only() -> None:
    callbacks, api, store = _bot(AckOutcome("unknown"))
    await callbacks.handle(_query())
    await callbacks.handle(_query(data="something-else"))
    await callbacks.handle({"id": "q2", "data": f"ack:{ALERT}"})  # no message: inline mode
    assert [a for _, a in api.answers] == ["Nu mai găsesc alerta."] * 3
    assert len(store.calls) == 1  # only the well-formed one reached the store
    assert api.edits == []


async def test_store_failure_answers_instead_of_leaving_the_button_spinning() -> None:
    class Broken(FakeStore):
        async def acknowledge(self, *args: str) -> AckOutcome:
            raise RuntimeError("db down")

    api = FakeApi()
    await AlertCallbacks(api, Broken(AckOutcome("unknown"))).handle(_query())
    assert api.answers == [("q1", "Nu am putut prelua alerta. Încearcă din aplicație.")]


async def test_link_bot_hands_callback_queries_to_the_callbacks() -> None:
    class LinkApi:
        async def get_updates(self, offset: int | None, timeout_s: int) -> list[dict[str, Any]]:
            return []

        async def send_message(self, chat_id: str, text: str) -> None:
            raise AssertionError("no reply to a button press")

        async def username(self) -> str | None:
            return "aivee_bot"

    class NoLinks:
        async def consume(self, code: str, chat_id: str, chat_title: str | None) -> Any:
            raise AssertionError("not a link code")

    callbacks, api, _ = _bot(AckOutcome("closed"))
    bot = TelegramLinkBot(LinkApi(), NoLinks(), callbacks)
    await bot.handle({"update_id": 3, "callback_query": _query()})
    assert api.answers == [("q1", "Alerta s-a închis")]
    # Without callbacks wired, a button press is ignored.
    await TelegramLinkBot(LinkApi(), NoLinks()).handle({"update_id": 4, "callback_query": _query()})
