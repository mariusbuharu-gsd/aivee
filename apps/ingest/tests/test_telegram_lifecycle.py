"""The Telegram side of an alert's end: remember the message, edit it, reply reminders."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from aivee_api.alerts.schemas import AlertView
from aivee_contracts.events import AlertEvent
from aivee_ingest.alert_message import AlertContext
from aivee_ingest.notify import LifecycleNotifier, LogNotifier
from aivee_ingest.sent import MemorySentMessages, SentMessage
from aivee_ingest.telegram import TelegramNotifier
from aivee_ingest.webpush import CompositeNotifier

AT = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
EVENT = AlertEvent(
    event_id="e1",
    rule_id="r1",
    camera_id="cam1",
    zone_id="t1",
    state="opened",
    at=AT,
    summary_ro="Masa 1: neservită",
)


def view(**kw: Any) -> AlertView:
    data: dict[str, Any] = {
        "event_id": "e1",
        "rule_id": "r1",
        "location_id": "demo",
        "camera_id": "cam1",
        "zone_id": "t1",
        "zone_name": "Masa 1",
        "summary_ro": "Masa 1: neservită",
        "opened_at": AT,
        "state": "arrived",
        "at": AT,
    }
    return AlertView.model_validate({**data, **kw})


async def _context(event: AlertEvent) -> AlertContext:
    return AlertContext(event, "Masa 1", "Terasa", "Sala")


def _notifier(
    result: dict[str, Any] | None = None, status: int = 200, body: str | None = None
) -> tuple[TelegramNotifier, list[httpx.Request], MemorySentMessages]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if body is not None:
            return httpx.Response(status, text=body)
        return httpx.Response(status, json={"ok": status == 200, "result": result or {}})

    sent = MemorySentMessages()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    n = TelegramNotifier(
        "TOKEN",
        "-100",
        client,
        context_for=_context,
        dashboard_url="https://aivee.example.ro",
        sent=sent,
    )
    return n, seen, sent


async def test_notify_remembers_the_message_it_sent(tmp_path: Path) -> None:
    n, _, sent = _notifier({"message_id": 42})
    await n.notify(EVENT, None)
    assert sent.items["e1"] == SentMessage("-100", 42, False)

    snap = tmp_path / "e1.jpg"
    snap.write_bytes(b"\xff\xd8x")
    n, _, sent = _notifier({"message_id": 43, "photo": [{}]})
    await n.notify(EVENT, snap)
    assert sent.items["e1"] == SentMessage("-100", 43, True)


async def test_resolved_edits_the_original_and_drops_the_buttons() -> None:
    n, seen, sent = _notifier()
    await sent.save("e1", SentMessage("-100", 42, False))
    v = view(acknowledged_by="Ana", acknowledged_at=AT)
    await n.alert_resolved(v, "✅ Rezolvat · un angajat a ajuns după 25 s")
    (req,) = seen
    assert req.url.path == "/botTOKEN/editMessageText"
    p = json.loads(req.content)
    assert (p["chat_id"], p["message_id"]) == ("-100", 42)
    assert p["reply_markup"] == {"inline_keyboard": []}
    assert p["text"].startswith("<b>✅ Rezolvat · un angajat a ajuns după 25 s</b>")
    assert "Masa 1" in p["text"] and "Preluată" not in p["text"]


async def test_resolved_photo_alert_edits_the_caption() -> None:
    n, seen, sent = _notifier()
    await sent.save("e1", SentMessage("-100", 42, True))
    await n.alert_resolved(view(), "⚪ Închisă · clientul a plecat")
    assert seen[0].url.path == "/botTOKEN/editMessageCaption"
    assert json.loads(seen[0].content)["caption"].startswith("<b>⚪ Închisă")


async def test_resolved_without_a_known_message_does_nothing() -> None:
    n, seen, _ = _notifier()
    await n.alert_resolved(view(), "✅ Rezolvat")
    assert seen == []


async def test_resolved_twice_is_not_an_error() -> None:
    n, _, sent = _notifier(status=400, body='{"ok":false,"description":"message is not modified"}')
    await sent.save("e1", SentMessage("-100", 42, False))
    await n.alert_resolved(view(), "✅ Rezolvat")


async def test_reminder_replies_to_the_alert_with_only_the_app_link() -> None:
    n, seen, sent = _notifier()
    await sent.save("e1", SentMessage("-100", 42, True))
    await n.alert_reminder(view(state="opened"), "⏰ Încă neservit: Masa 1, de 4 min")
    (req,) = seen
    p = json.loads(req.content)
    assert req.url.path == "/botTOKEN/sendMessage"
    assert p["text"] == "⏰ Încă neservit: Masa 1, de 4 min"
    assert p["reply_parameters"] == {"message_id": 42, "allow_sending_without_reply": True}
    buttons = [b["text"] for b in p["reply_markup"]["inline_keyboard"][0]]
    assert buttons == ["Vezi în aplicație"]


async def test_reminder_without_the_original_still_goes_to_the_chat() -> None:
    n, seen, _ = _notifier()
    await n.alert_reminder(view(state="opened"), "⏰ Încă neservit: Masa 1, de 2 min")
    p = json.loads(seen[0].content)
    assert p["chat_id"] == "-100" and "reply_parameters" not in p


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None: ...

    async def send_text(
        self, text: str, tag: str | None = None, *, title: Any = None, kind: Any
    ) -> None: ...

    async def alert_resolved(self, view: AlertView, line: str) -> None:
        self.calls.append(("resolved", line))

    async def alert_reminder(self, view: AlertView, text: str) -> None:
        raise RuntimeError("push service down")


class _Plain:
    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None: ...

    async def send_text(
        self, text: str, tag: str | None = None, *, title: Any = None, kind: Any
    ) -> None: ...


async def test_composite_forwards_to_lifecycle_notifiers_and_survives_failures() -> None:
    rec = _Recorder()
    both = CompositeNotifier([rec, _Plain(), LogNotifier()])
    assert isinstance(both, LifecycleNotifier)
    assert not isinstance(_Plain(), LifecycleNotifier)
    await both.alert_resolved(view(), "✅ Rezolvat")
    await both.alert_reminder(view(), "⏰")  # one failing never stops the others
    assert rec.calls == [("resolved", "✅ Rezolvat")]
