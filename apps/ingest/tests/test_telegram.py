import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from aivee_contracts.events import AlertEvent
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
