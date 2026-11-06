"""Re-alert after an unfulfilled acknowledgement (roadmap P0.4) — pure, no DB."""

from datetime import UTC, datetime, timedelta

from aivee_api.alerts.audit import realert_ro, realerted_entry
from aivee_api.alerts.domain import Lifecycle, realert_due
from aivee_api.alerts.schemas import AlertView

NOW = datetime(2026, 11, 6, 20, 0, tzinfo=UTC)
AFTER_S = 120


def ago(seconds: float) -> datetime:
    return NOW - timedelta(seconds=seconds)


def _acked(seconds_ago: float, **kw: datetime) -> Lifecycle:
    return Lifecycle(opened_at=ago(seconds_ago + 30), acknowledged_at=ago(seconds_ago), **kw)


def test_acknowledged_121_s_ago_is_due() -> None:
    assert realert_due(_acked(121), None, NOW, AFTER_S)


def test_acknowledged_119_s_ago_is_not_due() -> None:
    assert not realert_due(_acked(119), None, NOW, AFTER_S)


def test_only_once_already_realerted_is_not_due() -> None:
    assert not realert_due(_acked(300), ago(100), NOW, AFTER_S)


def test_arrived_or_closed_is_not_due() -> None:
    assert not realert_due(_acked(121, arrived_at=ago(10)), None, NOW, AFTER_S)
    assert not realert_due(_acked(121, closed_at=ago(10)), None, NOW, AFTER_S)


def test_never_acknowledged_is_not_due() -> None:
    assert not realert_due(Lifecycle(opened_at=ago(600)), None, NOW, AFTER_S)


def _view(**kw: object) -> AlertView:
    base: dict[str, object] = {
        "event_id": "e1",
        "rule_id": "r1",
        "location_id": "demo",
        "camera_id": "cam1",
        "zone_id": "t4",
        "zone_name": "Masa 4",
        "summary_ro": "Masa 4: neservită de 2 min",
        "opened_at": ago(160),
        "acknowledged_at": ago(125),
        "acknowledged_by": "Ana",
        "realerted_at": NOW,
        "state": "acknowledged",
        "at": ago(125),
        "device_id": "edge-01",
    }
    return AlertView.model_validate(base | kw)


def test_realert_text_names_who_confirmed_and_when() -> None:
    assert realert_ro(_view(), NOW) == "Masa 4: Ana a confirmat acum 2 min, încă nu a ajuns nimeni"
    later = realert_ro(_view(acknowledged_at=ago(200)), NOW)
    assert later == "Masa 4: Ana a confirmat acum 3 min, încă nu a ajuns nimeni"


def test_realert_view_carries_realerted_at() -> None:
    assert _view().realerted_at == NOW
    assert _view(realerted_at=None).realerted_at is None


def test_realerted_audit_entry_is_by_the_system() -> None:
    entry = realerted_entry(_view(), NOW)
    assert (entry.kind, entry.actor_kind, entry.target_id, entry.location_id) == (
        "alert.realerted",
        "system",
        "e1",
        "demo",
    )
    assert entry.summary_ro.startswith("Masa 4: Ana a confirmat")
    assert entry.after == {"realerted_at": NOW.isoformat()}
