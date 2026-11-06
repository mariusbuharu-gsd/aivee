"""`arrived`: staff stayed in an open alert's zone for at least `arrive_s` (D23)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from itertools import count

from aivee_contracts.events import AlertEvent
from aivee_contracts.geometry import Zone
from aivee_contracts.rules import Action, Condition, Rule
from aivee_edge.domain.engine import SituationEngine
from aivee_edge.domain.observation import BBox, Frame, TrackObs

CAM = "cam1"
TABLE = Zone(
    id="t1", name="Masa 1", tag="table", polygon=[(0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2)]
)
INSIDE: BBox = (0.08, 0.05, 0.12, 0.10)
OUTSIDE: BBox = (0.58, 0.55, 0.62, 0.60)


def rule(rule_id: str, *conds: Condition, cooldown_s: int = 0) -> Rule:
    return Rule(
        id=rule_id,
        camera_id=CAM,
        name=rule_id,
        prompt_ro="...",
        zone_tag="table",
        all_of=list(conds),
        action=Action(type="telegram"),
        cooldown_s=cooldown_s,
    )


def unattended(cooldown_s: int = 0) -> Rule:
    return rule(
        "unattended",
        Condition(kind="present", role="guest", min_duration_s=60),
        Condition(kind="absent", role="staff", min_duration_s=60),
        cooldown_s=cooldown_s,
    )


CALLS = rule("calls", Condition(kind="pose", role="guest", pose="raised_hand"))


def engine(*rules: Rule, arrive_s: float | None = 5.0, grace_s: float = 1.5) -> SituationEngine:
    ids: Iterator[int] = count(1)
    return SituationEngine(
        list(rules),
        [TABLE],
        id_factory=lambda: f"ev{next(ids)}",
        camera_id=CAM,
        grace_s=grace_s,
        arrive_s=arrive_s,
    )


GUEST = TrackObs(track_id=1, bbox=INSIDE)


def staff(bbox: BBox = INSIDE) -> TrackObs:
    return TrackObs(track_id=99, bbox=bbox, role="staff")


def run(
    eng: SituationEngine, start: int, end: int, *extra: TrackObs, hand: bool = False
) -> list[AlertEvent]:
    guest = TrackObs(track_id=1, bbox=INSIDE, raised_hand=hand)
    events: list[AlertEvent] = []
    for t in range(start, end + 1):
        events += eng.step(Frame(ts=t, tracks=(guest, *extra)))
    return events


def states(events: list[AlertEvent]) -> list[tuple[str, float]]:
    return [(e.state, e.at.timestamp()) for e in events]


def test_walking_past_does_not_count_and_keeps_the_alert_open() -> None:
    eng = engine(unattended())
    assert states(run(eng, 0, 60)) == [("opened", 60)]
    assert run(eng, 61, 63, staff()) == []  # 3 s in the zone: walking past
    assert run(eng, 64, 120, staff(OUTSIDE)) == []


def test_staff_staying_arrive_s_emits_arrived_then_closes() -> None:
    eng = engine(unattended())
    run(eng, 0, 60)
    run(eng, 61, 69)
    assert run(eng, 70, 74, staff()) == []
    events = run(eng, 75, 75, staff())
    assert states(events) == [("arrived", 75), ("closed", 75)]
    arrived = events[0]
    assert (arrived.rule_id, arrived.zone_id, arrived.camera_id) == ("unattended", "t1", CAM)
    assert arrived.summary_ro == "Masa 1: a venit un angajat"
    assert arrived.at == datetime.fromtimestamp(75, tz=UTC)
    assert run(eng, 76, 100, staff()) == []


def test_arrived_comes_once_even_when_the_alert_stays_open() -> None:
    """Arrival does not depend on the rule closing (nor on anyone acknowledging)."""
    eng = engine(CALLS)
    assert states(run(eng, 5, 5, hand=True)) == [("opened", 5)]
    assert states(run(eng, 6, 20, staff(), hand=True)) == [("arrived", 11)]
    assert states(run(eng, 21, 21, staff())) == [("closed", 21)]


def test_staff_already_there_counts_from_the_opening() -> None:
    eng = engine(CALLS)
    run(eng, 0, 4, staff())
    assert states(run(eng, 5, 12, staff(), hand=True)) == [("opened", 5), ("arrived", 10)]


def test_reopens_after_cooldown_and_arrives_again() -> None:
    eng = engine(unattended(cooldown_s=120))
    run(eng, 0, 60)
    assert [e.state for e in run(eng, 61, 66, staff())] == ["arrived", "closed"]
    # The waiter leaves; the guests wait again. Absence holds again at 126; cooldown until 180.
    assert run(eng, 67, 179, staff(OUTSIDE)) == []
    assert states(run(eng, 180, 180)) == [("opened", 180)]
    assert states(run(eng, 181, 190, staff())) == [("arrived", 186), ("closed", 186)]


def test_arrival_is_off_without_arrive_s() -> None:
    eng = engine(unattended(), arrive_s=None)
    run(eng, 0, 60)
    assert states(run(eng, 61, 61, staff())) == [("closed", 61)]
