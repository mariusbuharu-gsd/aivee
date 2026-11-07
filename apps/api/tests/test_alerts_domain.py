"""Alert lifecycle folding and service-time statistics (pure, no DB)."""

from datetime import UTC, datetime, timedelta

import pytest
from aivee_api.alerts.domain import (
    Lifecycle,
    duration_ro,
    percentile,
    service_stats,
    zone_name_from_summary,
)

T0 = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def test_opened_only_has_no_durations() -> None:
    life = Lifecycle(opened_at=T0)
    assert life.state == "opened"
    assert (life.wait_s, life.reaction_s, life.travel_s) == (None, None, None)
    assert life.last_change == T0


def test_full_lifecycle_durations() -> None:
    life = Lifecycle(opened_at=T0, acknowledged_at=at(20), arrived_at=at(130), closed_at=at(131))
    assert life.state == "closed"
    assert life.wait_s == 130  # arrived - opened
    assert life.reaction_s == 20  # acknowledged - opened
    assert life.travel_s == 110  # arrived - acknowledged
    assert life.last_change == at(131)


def test_acknowledged_then_waiting() -> None:
    life = Lifecycle(opened_at=T0, acknowledged_at=at(15))
    assert life.state == "acknowledged"
    assert (life.wait_s, life.reaction_s, life.travel_s) == (None, 15, None)


def test_arrival_without_ack_has_wait_but_no_reaction_or_travel() -> None:
    life = Lifecycle(opened_at=T0, arrived_at=at(42))
    assert life.state == "arrived"
    assert life.unacknowledged_arrival
    assert (life.wait_s, life.reaction_s, life.travel_s) == (42, None, None)


def test_closed_without_arrival_waits_until_closed() -> None:
    life = Lifecycle(opened_at=T0, closed_at=at(70))
    assert life.wait_s == 70
    assert not life.unacknowledged_arrival


def test_ack_after_arrival_has_no_travel() -> None:
    life = Lifecycle(opened_at=T0, arrived_at=at(30), acknowledged_at=at(40))
    assert life.travel_s is None
    assert life.reaction_s == 40


def test_percentile_interpolates() -> None:
    assert percentile([], 0.5) is None
    assert percentile([7.0], 0.9) == 7
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert percentile([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0], 0.9) == 91
    assert percentile([3.0, 1.0, 2.0], 0.5) == 2  # unsorted input


def test_service_stats_per_measure() -> None:
    lives = [
        Lifecycle(opened_at=T0, acknowledged_at=at(10), arrived_at=at(60), closed_at=at(60)),
        Lifecycle(opened_at=T0, acknowledged_at=at(30), arrived_at=at(120), closed_at=at(120)),
        Lifecycle(opened_at=T0, arrived_at=at(90), closed_at=at(90)),
        Lifecycle(opened_at=T0),  # still open: no measures
    ]
    stats = service_stats(lives)
    assert stats.alerts == 4
    assert stats.unacknowledged_arrivals == 1
    assert (stats.wait.count, stats.wait.median_s, stats.wait.p90_s) == (3, 90, pytest.approx(114))
    assert (stats.reaction.count, stats.reaction.median_s) == (2, 20)
    assert (stats.travel.count, stats.travel.median_s, stats.travel.p90_s) == (
        2,
        70,
        pytest.approx(86),
    )


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0, "0 s"), (42.4, "42 s"), (60, "1 min"), (130, "2 min 10 s"), (3599.6, "60 min")],
)
def test_duration_ro(seconds: float, text: str) -> None:
    assert duration_ro(seconds) == text


def test_zone_name_from_summary() -> None:
    assert zone_name_from_summary("Masa 4: neservită de 2 min") == "Masa 4"
    assert zone_name_from_summary("fără două puncte") is None


# -- closed by the system when the device goes away --------------------------------------


@pytest.mark.parametrize(
    ("before", "after", "reason"),
    [
        ("online", "offline", "device_offline"),
        ("offline", "offline", "device_offline"),  # a late or repeated offline: still close
        (None, "offline", "device_offline"),
        ("offline", "online", "device_restarted"),  # fresh engine: old alerts are stale
        ("online", "online", None),  # retained re-delivery (ingest restart): keep them open
        (None, "online", None),  # first time seen: nothing of it can be open
    ],
)
def test_system_close_reason(before: str | None, after: str, reason: str | None) -> None:
    from aivee_api.alerts.domain import system_close_reason

    assert system_close_reason(before, after) == reason


def test_closed_by() -> None:
    from aivee_api.alerts.domain import closed_by

    assert closed_by(None, None) is None
    assert closed_by(at(1), None) == "edge"
    assert closed_by(at(1), "device_offline") == "system"


def test_system_close_texts() -> None:
    from aivee_api.alerts.domain import device_closed_note_ro, system_close_summary_ro

    assert (
        system_close_summary_ro("Masa 1", "device_offline")
        == "Alerta de la Masa 1 s-a închis: dispozitivul s-a deconectat"
    )
    assert (
        system_close_summary_ro("Masa 1", "device_restarted")
        == "Alerta de la Masa 1 s-a închis: dispozitivul a repornit"
    )
    assert (
        system_close_summary_ro("Masa 1", "video_end")
        == "Alerta de la Masa 1 s-a închis: clipul s-a terminat"
    )
    note = device_closed_note_ro
    assert note("edge-01", "device_offline", 1) == "edge-01 s-a deconectat — o alertă închisă"
    assert note("edge-01", "device_offline", 2) == "edge-01 s-a deconectat — 2 alerte închise"
    assert note("edge-01", "device_restarted", 3) == "edge-01 a repornit — 3 alerte închise"
    assert note("edge-01", "device_offline", 21) == "edge-01 s-a deconectat — 21 de alerte închise"
