from datetime import UTC, datetime, timedelta

from aivee_api.alerts.schemas import AlertView
from aivee_contracts.rules import Condition
from aivee_ingest.lifecycle import (
    closed_line,
    is_guest_rule,
    left_ro,
    reminder_ro,
    resolved_line,
)

OPENED = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def view(**kw: object) -> AlertView:
    data: dict[str, object] = {
        "event_id": "e1",
        "rule_id": "r1",
        "location_id": "demo",
        "camera_id": "cam1",
        "zone_id": "t1",
        "zone_name": "Masa 1",
        "summary_ro": "Masa 1: neservită",
        "opened_at": OPENED,
        "state": "opened",
        "at": OPENED,
    }
    return AlertView.model_validate({**data, **kw})


def test_resolved_line_names_the_wait_and_who_took_it() -> None:
    assert resolved_line(view(wait_s=25)) == "✅ Rezolvat · un angajat a ajuns după 25 s"
    assert (
        resolved_line(view(wait_s=130, acknowledged_by="Ana"))
        == "✅ Rezolvat · un angajat a ajuns după 2 min 10 s · preluată de Ana"
    )


def test_guest_left_texts() -> None:
    v = view(wait_s=190)
    assert left_ro(v, guest=True) == (
        "👋 Clientul a plecat de la Masa 1 fără să fie servit (a așteptat 3 min 10 s)"
    )
    assert closed_line(guest=True) == "⚪ Închisă · clientul a plecat"
    # A fire or a missing glass has no guest who waited.
    assert left_ro(v, guest=False) == "⚪ Alerta de la Masa 1 s-a închis singură după 3 min 10 s"
    assert closed_line(guest=False) == "⚪ Închisă · situația s-a încheiat"


def test_reminder_counts_whole_minutes_since_opening() -> None:
    v = view()
    now = OPENED + timedelta(minutes=4, seconds=20)
    assert reminder_ro(v, now, guest=True) == "⏰ Încă neservit: Masa 1, de 4 min"
    assert reminder_ro(v, OPENED + timedelta(seconds=30), guest=False) == (
        "⏰ Încă nerezolvat: Masa 1, de 1 min"
    )


def test_guest_rules_are_the_waiting_ones() -> None:
    assert is_guest_rule([Condition(kind="absent", role="staff", min_duration_s=60)])
    assert is_guest_rule([Condition(kind="pose", role="guest", pose="raised_hand")])
    assert not is_guest_rule([Condition(kind="visual", label_ro="foc", positive=["fire"])])
    assert is_guest_rule([])  # unknown rule: the restaurant default
