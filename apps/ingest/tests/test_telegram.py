import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from aivee_contracts.events import AlertEvent
from aivee_contracts.rules import Condition
from aivee_ingest.alert_message import AlertContext
from aivee_ingest.notify import LogNotifier, alert_text
from aivee_ingest.telegram import TelegramNotifier

EVENT = AlertEvent(
    event_id="e1",
    rule_id="r1",
    camera_id="cam1",
    zone_id="masa-1",
    state="opened",
    at=datetime(2026, 11, 6, 12, 30, tzinfo=UTC),
    summary_ro="Masa 1 așteaptă de 5 minute",
    snapshot=True,
)


def _notifier(status: int = 200) -> tuple[TelegramNotifier, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={"ok": status == 200})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return TelegramNotifier("TOKEN", "-100", client), seen


def test_alert_text_is_romanian_and_mentions_zone() -> None:
    text = alert_text(EVENT)
    assert "Masa 1 așteaptă de 5 minute" in text
    assert "Zona: masa-1" in text and "Camera: cam1" in text
    assert "Ora: 14:30" in text  # 12:30 UTC in Bucharest (EET)


async def test_sends_photo_when_snapshot_exists(tmp_path: Path) -> None:
    snap = tmp_path / "e1.jpg"
    snap.write_bytes(b"\xff\xd8blurred")
    notifier, seen = _notifier()
    await notifier.notify(EVENT, snap)
    (req,) = seen
    assert req.url.path == "/botTOKEN/sendPhoto"
    body = req.content
    assert b"blurred" in body and b"-100" in body
    assert "Masa 1 așteaptă".encode() in body


async def test_sends_message_without_snapshot() -> None:
    notifier, seen = _notifier()
    await notifier.notify(EVENT, None)
    (req,) = seen
    assert req.url.path == "/botTOKEN/sendMessage"
    payload = json.loads(req.content)
    assert payload["chat_id"] == "-100" and "Masa 1" in payload["text"]


async def test_missing_snapshot_file_falls_back_to_message(tmp_path: Path) -> None:
    notifier, seen = _notifier()
    await notifier.notify(EVENT, tmp_path / "gone.jpg")
    assert seen[0].url.path.endswith("/sendMessage")


async def test_api_error_raises_without_leaking_token() -> None:
    notifier, _ = _notifier(status=403)
    with pytest.raises(RuntimeError) as err:
        await notifier.notify(EVENT, None)
    assert "TOKEN" not in str(err.value)


async def test_log_notifier_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    await LogNotifier().notify(EVENT, None)
    assert "Masa 1 așteaptă" in caplog.text


def _recording_client() -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


async def test_prefix_marks_alert_and_follow_up_messages() -> None:
    client, seen = _recording_client()
    notifier = TelegramNotifier("TOKEN", "-100", client, prefix="[test]")
    await notifier.notify(EVENT, None)
    await notifier.send_text("Ana a ajuns la Masa 1 după 2 min 10 s", kind="arrived")
    texts = [json.loads(r.content)["text"] for r in seen]
    assert texts[0].startswith("[test] 🔴 <b>Masa 1")
    assert texts[1] == "[test] Ana a ajuns la Masa 1 după 2 min 10 s"
    assert all(r.url.path == "/botTOKEN/sendMessage" for r in seen)


async def test_follow_up_error_raises_without_leaking_token() -> None:
    notifier, _ = _notifier(status=500)
    with pytest.raises(RuntimeError) as err:
        await notifier.send_text("x", kind="arrived")
    assert "TOKEN" not in str(err.value)


async def test_the_locations_chat_wins_over_the_default_for_alert_and_follow_up() -> None:
    client, seen = _recording_client()

    async def chat_for(event_id: str) -> str | None:
        return "-200" if event_id == "e1" else None

    notifier = TelegramNotifier("TOKEN", "-100", client, chat_for=chat_for)
    await notifier.notify(EVENT, None)
    await notifier.notify(EVENT.model_copy(update={"event_id": "e9"}), None)
    await notifier.send_text("Ana a ajuns", tag="e1", kind="arrived")
    await notifier.send_text("fără alertă", kind="device")
    assert [json.loads(r.content)["chat_id"] for r in seen] == ["-200", "-100", "-200", "-100"]


async def test_no_chat_at_all_sends_nothing(caplog: pytest.LogCaptureFixture) -> None:
    client, seen = _recording_client()

    async def none(_: str) -> str | None:
        return None

    notifier = TelegramNotifier("TOKEN", None, client, chat_for=none)
    await notifier.notify(EVENT, None)
    await notifier.send_text("x", tag="e1", kind="realert")
    assert seen == [] and "no Telegram chat" in caplog.text


async def _names(event: AlertEvent) -> AlertContext:
    return AlertContext(
        event,
        zone_name="Masa 1",
        location_name="Terasa <demo>",
        camera_name="Sala principală",
        conditions=[Condition(kind="absent", role="staff", min_duration_s=60)],
    )


async def test_alert_is_html_with_names_and_the_preiau_button() -> None:
    client, seen = _recording_client()
    notifier = TelegramNotifier("TOKEN", "-100", client, context_for=_names)
    await notifier.notify(EVENT, None)
    (req,) = seen
    payload = json.loads(req.content)
    assert payload["parse_mode"] == "HTML"
    assert payload["text"] == (
        "🔴 <b>Masa 1 așteaptă de 1 min</b>\nNu a venit nimeni la client.\n\n"
        "📍 Terasa &lt;demo&gt; · Sala principală · 14:30"
    )
    assert "reply_markup" not in payload  # no "Preiau ✋" any more, and no public dashboard
    assert "cam1" not in payload["text"] and "masa-1" not in payload["text"]


async def test_photo_caption_carries_the_keyboard_and_the_dashboard_link(tmp_path: Path) -> None:
    snap = tmp_path / "e1.jpg"
    snap.write_bytes(b"\xff\xd8blurred")
    client, seen = _recording_client()
    notifier = TelegramNotifier(
        "TOKEN", "-100", client, context_for=_names, dashboard_url="https://aivee.example.com"
    )
    await notifier.notify(EVENT, snap)
    (req,) = seen
    assert req.url.path == "/botTOKEN/sendPhoto"
    body = req.content.decode("utf-8", "replace")
    assert 'name="parse_mode"' in body
    assert "<b>Masa 1 așteaptă de 1 min</b>" in body
    markup = body.split('name="reply_markup"')[1].split("\r\n\r\n", 1)[1].split("\r\n")[0]
    assert json.loads(markup)["inline_keyboard"] == [
        [{"text": "Vezi în aplicație", "url": "https://aivee.example.com/alerte"}]
    ]


async def test_a_refused_rich_send_is_retried_once_as_plain_text(tmp_path: Path) -> None:
    snap = tmp_path / "e1.jpg"
    snap.write_bytes(b"\xff\xd8blurred")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(400, json={"ok": False, "description": "Bad Request: button"})
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    notifier = TelegramNotifier("TOKEN", "-100", client, context_for=_names, prefix="[test]")
    await notifier.notify(EVENT, snap)
    assert [r.url.path for r in seen] == ["/botTOKEN/sendPhoto", "/botTOKEN/sendMessage"]
    retry = json.loads(seen[1].content)
    assert set(retry) == {"chat_id", "text"}  # no parse mode, no keyboard
    assert retry["text"].startswith("[test] 🔴 Masa 1 așteaptă de 1 min\n")
    assert "Terasa <demo>" in retry["text"]


async def test_a_failing_plain_retry_still_raises() -> None:
    notifier, seen = _notifier(status=400)
    with pytest.raises(RuntimeError):
        await notifier.notify(EVENT, None)
    assert len(seen) == 2


async def test_names_lookup_failure_falls_back_to_the_edge_summary() -> None:
    async def broken(_: AlertEvent) -> AlertContext:
        raise RuntimeError("db down")

    client, seen = _recording_client()
    notifier = TelegramNotifier("TOKEN", "-100", client, context_for=broken)
    await notifier.notify(EVENT, None)
    assert json.loads(seen[0].content)["text"].startswith("🔴 <b>Masa 1 așteaptă de 5 minute</b>")
