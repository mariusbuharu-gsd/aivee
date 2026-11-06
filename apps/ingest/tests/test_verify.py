"""Alert verification with a deterministic fake verifier and in-memory store (no DB)."""

import asyncio
import base64
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest
from aivee_api.push.sender import PushKind
from aivee_contracts.events import AlertEvent, ObjectChange, Verification, before_snapshot_id
from aivee_ingest.config import IngestSettings
from aivee_ingest.verify import (
    AlertVerification,
    ClaudeAlertVerifier,
    VerificationAnswer,
    VerifyContext,
    VerifyKind,
    build_verifier,
    question_ro,
)

AFTER, BEFORE = b"\xff\xd8after", b"\xff\xd8before"


def _event(*, gone: bool = False, snapshot: bool = True) -> AlertEvent:
    return AlertEvent(
        event_id="ev1",
        rule_id="r1",
        camera_id="cam1",
        zone_id="t1",
        state="opened",
        at=datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
        summary_ro="Masa 1: a dispărut paharul de vin" if gone else "Masa 1: neservită de 1 min",
        snapshot=snapshot,
        object_change=ObjectChange(objects=["wine glass"], before_snapshot=True) if gone else None,
    )


class FakeVerifier:
    """Answers `status` for every call and remembers what it was asked."""

    def __init__(self, status: str = "confirmed", delay_s: float = 0.0, fail: bool = False) -> None:
        self.status = status
        self.delay_s = delay_s
        self.fail = fail
        self.calls: list[tuple[str, str, list[bytes], VerifyKind, list[str]]] = []

    async def verify(
        self,
        rule_prompt_ro: str,
        zone_name: str,
        images: Sequence[bytes],
        kind: VerifyKind,
        objects: Sequence[str] = (),
    ) -> Verification:
        self.calls.append((rule_prompt_ro, zone_name, list(images), kind, list(objects)))
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.fail:
            raise RuntimeError("boom")
        return Verification.model_validate(
            {
                "status": self.status,
                "summary_ro": f"{zone_name}: a dispărut paharul de vin",
                "object_ro": "pahar de vin",
                "model": "fake",
            }
        )


class MemoryStore:
    def __init__(self) -> None:
        self.claimed: set[str] = set()
        self.saved: dict[str, list[Verification]] = {}

    async def claim(self, alert_id: str) -> bool:
        if alert_id in self.claimed:
            return False
        self.claimed.add(alert_id)
        return True

    async def context(self, event: AlertEvent) -> VerifyContext:
        return VerifyContext("Anunță-mă dacă dispare un pahar de pe masă", "Masa 1")

    async def save(self, alert_id: str, verification: Verification) -> None:
        self.saved.setdefault(alert_id, []).append(verification)


class Notifier:
    def __init__(self) -> None:
        self.notified: list[tuple[AlertEvent, Path | None]] = []

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        self.notified.append((event, snapshot))

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None, kind: PushKind
    ) -> None:
        raise AssertionError("not used")


def _service(
    tmp_path: Path, verifier: FakeVerifier, *, before: bool = True, timeout_s: float = 1.0
) -> tuple[AlertVerification, MemoryStore, Notifier]:
    (tmp_path / "ev1.jpg").write_bytes(AFTER)
    if before:
        (tmp_path / f"{before_snapshot_id('ev1')}.jpg").write_bytes(BEFORE)
    store, notifier = MemoryStore(), Notifier()
    service = AlertVerification(
        verifier, store, notifier, tmp_path, timeout_s=timeout_s, snapshot_wait_s=0.2
    )
    return service, store, notifier


async def test_confirmed_object_gone_sends_before_and_after_and_notifies_the_ai_summary(
    tmp_path: Path,
) -> None:
    verifier = FakeVerifier("confirmed")
    service, store, notifier = _service(tmp_path, verifier)

    result = await service.run(_event(gone=True))

    assert result.status == "confirmed"
    [(prompt, zone, images, kind, objects)] = verifier.calls
    assert (prompt, zone, kind, objects) == (
        "Anunță-mă dacă dispare un pahar de pe masă",
        "Masa 1",
        "object_gone",
        ["wine glass"],
    )
    assert images == [BEFORE, AFTER]
    [saved] = store.saved["ev1"]
    assert saved.status == "confirmed" and saved.latency_ms is not None
    [(event, snapshot)] = notifier.notified
    assert event.summary_ro == "Masa 1: a dispărut paharul de vin"
    assert snapshot == tmp_path / "ev1.jpg"


async def test_rejected_is_stored_and_not_notified(tmp_path: Path) -> None:
    service, store, notifier = _service(tmp_path, FakeVerifier("rejected"))
    result = await service.run(_event(gone=True))
    assert result.status == "rejected"
    assert [v.status for v in store.saved["ev1"]] == ["rejected"]
    assert notifier.notified == []


async def test_other_kinds_send_the_single_snapshot(tmp_path: Path) -> None:
    verifier = FakeVerifier("confirmed")
    service, _, notifier = _service(tmp_path, verifier, before=False)
    await service.run(_event())
    [(_, _, images, kind, objects)] = verifier.calls
    assert (images, kind, objects) == ([AFTER], "snapshot", [])
    assert len(notifier.notified) == 1


@pytest.mark.parametrize(
    ("verifier", "event", "before"),
    [
        (FakeVerifier(fail=True), _event(gone=True), True),  # SDK error
        (FakeVerifier(delay_s=5), _event(gone=True), True),  # timeout
        (FakeVerifier(), _event(gone=True), False),  # no before image: nothing to compare
        (FakeVerifier(), _event(snapshot=False), False),  # no image at all
    ],
    ids=["error", "timeout", "no-before", "no-image"],
)
async def test_unavailable_still_notifies_as_a_normal_alert(
    tmp_path: Path, verifier: FakeVerifier, event: AlertEvent, before: bool
) -> None:
    service, store, notifier = _service(tmp_path, verifier, before=before, timeout_s=0.1)
    result = await service.run(event)
    assert result.status == "unavailable"
    assert [v.status for v in store.saved["ev1"]] == ["unavailable"]
    [(notified, _)] = notifier.notified
    assert notified.summary_ro == event.summary_ro  # the edge's own text


async def test_at_most_one_verification_per_alert(tmp_path: Path) -> None:
    verifier = FakeVerifier("confirmed")
    service, _, notifier = _service(tmp_path, verifier)
    await service.run(_event(gone=True))
    assert await service.run(_event(gone=True)) is None
    assert len(verifier.calls) == 1 and len(notifier.notified) == 1


def test_question_is_built_from_the_rules_own_text() -> None:
    q = question_ro("Anunță-mă dacă la o masă nu vine nimeni de 1 minut", "Masa 1", "snapshot", [])
    assert "«Anunță-mă dacă la o masă nu vine nimeni de 1 minut»" in q
    assert "Masa 1" in q and "da/nu" in q
    gone = question_ro("Anunță-mă dacă dispare un pahar", "Masa 2", "object_gone", ["wine glass"])
    assert "imaginea 1" in gone.lower() and "wine glass" in gone


def test_build_verifier_needs_the_flag_and_a_key() -> None:
    assert build_verifier(IngestSettings(verify_alerts=False, anthropic_api_key="k")) is None
    assert build_verifier(IngestSettings(verify_alerts=True, anthropic_api_key=None)) is None
    verifier = build_verifier(
        IngestSettings(verify_alerts=True, anthropic_api_key="k", verify_model="m")
    )
    assert isinstance(verifier, ClaudeAlertVerifier)


# -- the real adapter, against a fake SDK client ----------------------------------------


class FakeMessages:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.kwargs: dict[str, Any] = {}

    async def parse(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def _client(response: Any = None, error: Exception | None = None) -> Any:
    return SimpleNamespace(messages=FakeMessages(response, error))


def _answer(yes: bool, stop_reason: str = "end_turn") -> Any:
    parsed = VerificationAnswer(
        yes=yes, summary_ro="Masa 1: a dispărut paharul de vin", object_ro="pahar de vin"
    )
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed)


async def test_claude_verifier_sends_both_images_in_order_with_the_rule_question() -> None:
    client = _client(_answer(True))
    v = await ClaudeAlertVerifier(client, model="claude-opus-5-5").verify(
        "Anunță-mă dacă dispare un pahar de pe masă",
        "Masa 1",
        [BEFORE, AFTER],
        "object_gone",
        ["wine glass"],
    )
    assert v == Verification(
        status="confirmed",
        summary_ro="Masa 1: a dispărut paharul de vin",
        object_ro="pahar de vin",
        model="claude-opus-5-5",
    )
    kw = client.messages.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"] == {"effort": "low"}
    assert kw["output_format"] is VerificationAnswer
    assert "cache_control" in kw["system"][0]
    [message] = kw["messages"]
    images = [b for b in message["content"] if b["type"] == "image"]
    assert [base64.b64decode(b["source"]["data"]) for b in images] == [BEFORE, AFTER]
    assert all(b["source"]["media_type"] == "image/jpeg" for b in images)
    assert "«Anunță-mă dacă dispare un pahar de pe masă»" in message["content"][-1]["text"]


async def test_claude_verifier_no_is_rejected() -> None:
    v = await ClaudeAlertVerifier(_client(_answer(False))).verify(
        "r", "Masa 1", [AFTER], "snapshot"
    )
    assert v.status == "rejected"


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
async def test_claude_verifier_unusable_answers_are_unavailable(stop_reason: str) -> None:
    client = _client(_answer(True, stop_reason))
    v = await ClaudeAlertVerifier(client).verify("r", "Masa 1", [AFTER], "snapshot")
    assert v.status == "unavailable"


async def test_claude_verifier_api_errors_are_unavailable() -> None:
    error = anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    v = await ClaudeAlertVerifier(_client(error=error)).verify("r", "Masa 1", [AFTER], "snapshot")
    assert v.status == "unavailable"
