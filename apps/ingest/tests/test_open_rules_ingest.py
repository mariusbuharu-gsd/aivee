"""Open rules in ingest: the verification question and the Telegram text per kind."""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from aivee_api.push.sender import PushKind
from aivee_contracts.events import AlertEvent, Verification
from aivee_contracts.rules import ANYWHERE_TAG, Condition
from aivee_ingest.alert_message import AlertContext, headline_explanation, render
from aivee_ingest.verify import (
    AlertVerification,
    VerifyContext,
    VerifyKind,
    looked_for,
    question_ro,
    verify_kind,
)

AT = datetime(2026, 11, 6, 19, 30, tzinfo=UTC)
FIRE = Condition(
    kind="visual",
    positive=["a photo of fire", "flames"],
    negative=["a photo of a room"],
    min_duration_s=3,
    label_ro="foc",
)
BEAR = Condition(kind="object_present", objects=["bear"], min_duration_s=2, label_ro="urs")
WAIT = [Condition(kind="present", role="guest"), Condition(kind="absent", role="staff")]


def _event(summary: str) -> AlertEvent:
    return AlertEvent(
        event_id="ev1",
        rule_id="r1",
        camera_id="cam-01",
        zone_id=ANYWHERE_TAG,
        state="opened",
        at=AT,
        summary_ro=summary,
        snapshot=True,
    )


def _ctx(
    conditions: list[Condition], summary: str, verification: Verification | None = None
) -> AlertContext:
    zone = summary.partition(":")[0]
    return AlertContext(
        _event(summary),
        zone_name=zone,
        location_name="Terasa demo",
        camera_name=zone,
        conditions=conditions,
        verification=verification,
    )


# -- Telegram text --------------------------------------------------------------------------


def test_visual_alert_says_possible_and_what() -> None:
    ctx = _ctx([FIRE], "Sala principală: posibil foc")
    assert headline_explanation(ctx) == ("Sala principală: posibil foc", "Verifică imediat locul.")
    assert render(ctx).splitlines()[0] == "🔴 <b>Sala principală: posibil foc</b>"


def test_object_present_alert_names_the_object_from_the_edge() -> None:
    ctx = _ctx([BEAR], "Terasă: a apărut un urs")
    assert headline_explanation(ctx) == ("Terasă: a apărut un urs", "Verifică locul.")


def test_object_present_without_an_edge_name_uses_the_label() -> None:
    ctx = _ctx([BEAR], "Terasă: ceva")
    assert headline_explanation(ctx)[0] == "Terasă: a apărut un urs"


def test_confirmed_check_replaces_the_explanation_with_the_ai_summary() -> None:
    v = Verification(status="confirmed", summary_ro="Sala principală: flăcări lângă bar")
    ctx = _ctx([FIRE], "Sala principală: posibil foc", v)
    assert headline_explanation(ctx) == (
        "Sala principală: posibil foc",
        "Sala principală: flăcări lângă bar",
    )


def test_existing_kinds_keep_their_text() -> None:
    ctx = _ctx(WAIT, "Masa 1: neservită de 0 s")
    assert headline_explanation(ctx)[1] == "Nu a venit nimeni la client."


# -- verification question ------------------------------------------------------------------


def test_open_rules_ask_the_visible_question() -> None:
    assert verify_kind(_event("x"), [FIRE]) == "visible"
    assert verify_kind(_event("x"), [BEAR]) == "visible"
    assert verify_kind(_event("x"), WAIT) == "snapshot"
    assert looked_for([FIRE, BEAR, *WAIT]) == ["foc", "urs"]
    unlabeled = [FIRE.model_copy(update={"label_ro": ""}), BEAR.model_copy(update={"label_ro": ""})]
    assert looked_for(unlabeled) == ["a photo of fire", "bear"]


def test_visible_question_is_built_from_the_rule_text_and_rejects_screens() -> None:
    q = question_ro("dacă e foc", "Sala principală", "visible", ["foc"])
    assert "«dacă e foc»" in q and "Sala principală" in q
    assert "Se vede cu adevărat în imagine: foc?" in q and "ecran" in q
    q_bear = question_ro("anunță-mă dacă vine un urs", "Terasă", "visible", ["urs"])
    assert "Se vede cu adevărat în imagine: urs?" in q_bear


class Verifier:
    def __init__(self, status: str) -> None:
        self.status = status
        self.calls: list[tuple[str, VerifyKind, list[str]]] = []

    async def verify(
        self,
        rule_prompt_ro: str,
        zone_name: str,
        images: Sequence[bytes],
        kind: VerifyKind,
        objects: Sequence[str] = (),
    ) -> Verification:
        self.calls.append((rule_prompt_ro, kind, list(objects)))
        return Verification.model_validate(
            {"status": self.status, "summary_ro": f"{zone_name}: nu se vede foc", "model": "f"}
        )


class Store:
    async def claim(self, alert_id: str) -> bool:
        return True

    async def context(self, event: AlertEvent) -> VerifyContext:
        return VerifyContext("dacă e foc", "Sala principală", [FIRE])

    async def save(self, alert_id: str, verification: Verification) -> None:
        pass


class Notifier:
    def __init__(self) -> None:
        self.sent: list[AlertEvent] = []

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        self.sent.append(event)

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None, kind: PushKind
    ) -> None:
        raise AssertionError("not used")


async def test_rejected_visual_alert_is_not_notified(tmp_path: Path) -> None:
    (tmp_path / "ev1.jpg").write_bytes(b"\xff\xd8jpeg")
    verifier, notifier = Verifier("rejected"), Notifier()
    service = AlertVerification(verifier, Store(), notifier, tmp_path, snapshot_wait_s=0.2)
    result = await service.run(_event("Sala principală: posibil foc"))
    assert result is not None and result.status == "rejected"
    assert notifier.sent == []
    assert verifier.calls == [("dacă e foc", "visible", ["foc"])]


async def test_confirmed_visual_alert_is_notified_with_the_ai_summary(tmp_path: Path) -> None:
    (tmp_path / "ev1.jpg").write_bytes(b"\xff\xd8jpeg")
    notifier = Notifier()
    service = AlertVerification(
        Verifier("confirmed"), Store(), notifier, tmp_path, snapshot_wait_s=0.2
    )
    await service.run(_event("Sala principală: posibil foc"))
    assert [e.summary_ro for e in notifier.sent] == ["Sala principală: nu se vede foc"]
