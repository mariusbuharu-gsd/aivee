"""A capture gap (the stream stalls or reconnects) is not absence (E26).

When a frame arrives more than the gap threshold after the previous one, every zone
timer is shifted forward by the gap: timers freeze during it and the grace window
starts again from the first frame after it.
"""

from collections.abc import Iterator
from itertools import count

from aivee_contracts.events import AlertEvent
from aivee_contracts.geometry import Zone
from aivee_contracts.rules import Action, Condition, Rule
from aivee_edge.domain.engine import STREAM_GAP_MIN_S, SituationEngine, stream_gap_s
from aivee_edge.domain.objects import GONE_CONFIRM_S
from aivee_edge.domain.observation import BBox, Frame, ObjectObs, TrackObs

CAM = "cam1"
TABLE = Zone(
    id="t1", name="Masa 1", tag="table", polygon=[(0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4)]
)
INSIDE: BBox = (0.08, 0.05, 0.12, 0.10)
GLASS_BOX: BBox = (0.1, 0.1, 0.15, 0.3)
GRACE_S = 5.0
GAP = 30


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


UNSERVED = rule(
    "unserved",
    Condition(kind="present", role="guest", min_duration_s=60),
    Condition(kind="absent", role="staff", min_duration_s=60),
)


def calls(cooldown_s: int = 0) -> Rule:
    return rule(
        "calls", Condition(kind="pose", role="guest", pose="raised_hand"), cooldown_s=cooldown_s
    )


GONE = rule("gone", Condition(kind="object_gone", objects=["wine glass"], min_duration_s=10))


def engine(
    *rules: Rule, grace_s: float = GRACE_S, bridge: bool = True, arrive_s: float | None = 5.0
) -> SituationEngine:
    ids: Iterator[int] = count(1)
    return SituationEngine(
        list(rules),
        [TABLE],
        id_factory=lambda: f"ev{next(ids)}",
        camera_id=CAM,
        grace_s=grace_s,
        arrive_s=arrive_s,
        gap_s=stream_gap_s(grace_s) if bridge else None,
    )


GUEST = TrackObs(track_id=1, bbox=INSIDE)
STAFF = TrackObs(track_id=99, bbox=INSIDE, role="staff")


def run(eng: SituationEngine, start: float, end: float, *tracks: TrackObs) -> list[AlertEvent]:
    events: list[AlertEvent] = []
    for t in range(int(start), int(end) + 1):
        events += eng.step(Frame(ts=float(t), tracks=tracks))
    return events


def states(events: list[AlertEvent]) -> list[tuple[str, float]]:
    return [(e.state, e.at.timestamp()) for e in events]


# -- threshold -----------------------------------------------------------------------


def test_threshold_is_grace_with_a_floor() -> None:
    assert stream_gap_s(5.0) == 5.0
    assert stream_gap_s(0.0) == STREAM_GAP_MIN_S
    assert stream_gap_s(1.5) == STREAM_GAP_MIN_S


# -- presence ------------------------------------------------------------------------


def test_gap_then_empty_frames_then_guest_back_does_not_close() -> None:
    eng = engine(UNSERVED)
    assert states(run(eng, 0, 130, GUEST)) == [("opened", 60)]
    # USB drop: no frame for 30 s, then ByteTrack needs a few frames to confirm the guest.
    events = run(eng, 130 + GAP, 132 + GAP)
    events += run(eng, 133 + GAP, 200, GUEST)
    assert events == []


def test_gap_reports_the_bridged_seconds_once() -> None:
    eng = engine(UNSERVED)
    run(eng, 0, 10, GUEST)
    eng.step(Frame(ts=10.0 + GAP, tracks=(GUEST,)))
    assert eng.last_gap_s == GAP
    eng.step(Frame(ts=11.0 + GAP, tracks=(GUEST,)))
    assert eng.last_gap_s is None


def test_guest_really_gone_after_gap_closes_grace_after_the_gap_ends() -> None:
    eng = engine(UNSERVED)
    run(eng, 0, 130, GUEST)
    events = run(eng, 130 + GAP, 200)
    # Gap ends at 160; the guest counts as present for grace_s more, gone at 166.
    assert states(events) == [("closed", 130 + GAP + GRACE_S + 1)]


def test_without_gap_behaviour_is_unchanged() -> None:
    eng = engine(UNSERVED)
    assert states(run(eng, 0, 130, GUEST)) == [("opened", 60)]
    assert states(run(eng, 131, 200)) == [("closed", 130 + GRACE_S + 1)]
    assert eng.last_gap_s is None


def test_without_bridging_the_gap_counts_as_absence() -> None:
    """The bug as seen live: the first frames after the gap close the alert."""
    eng = engine(UNSERVED, bridge=False)
    run(eng, 0, 130, GUEST)
    assert states(run(eng, 130 + GAP, 130 + GAP)) == [("closed", 130 + GAP)]


def test_durations_exclude_the_gap() -> None:
    """ "Neservită de 1 min" means 1 min of observed time, not wall time."""
    eng = engine(UNSERVED)
    assert run(eng, 0, 30, GUEST) == []
    assert states(run(eng, 30 + GAP, 100, GUEST)) == [("opened", 60 + GAP)]


# -- engine times: arrival and cooldown ----------------------------------------------


def test_arrival_does_not_count_the_gap() -> None:
    eng = engine(calls())
    hand = TrackObs(track_id=1, bbox=INSIDE, raised_hand=True)
    run(eng, 0, 4, STAFF)
    assert states(run(eng, 5, 7, hand, STAFF)) == [("opened", 5)]
    # Gap of 30 s right after the opening: arrival still needs arrive_s observed after it.
    events = run(eng, 7 + GAP, 20 + GAP, hand, STAFF)
    assert states(events) == [("arrived", 10 + GAP)]


def test_cooldown_is_wall_clock_and_not_restarted_by_the_gap() -> None:
    """Cooldown limits how often staff are paged: it is measured in wall time, so a gap
    neither restarts it (a real call after a long outage is not swallowed) nor lets an
    alert re-open before `cooldown_s` has passed since it opened."""
    eng = engine(calls(cooldown_s=60))
    hand = TrackObs(track_id=1, bbox=INSIDE, raised_hand=True)
    assert states(run(eng, 0, 0, hand)) == [("opened", 0)]
    assert states(run(eng, 1, 1, GUEST)) == [("closed", 1)]
    # Gap of 30 s, shorter than the cooldown: no immediate re-open after it.
    assert run(eng, 1 + GAP, 59, hand) == []
    assert states(run(eng, 60, 60, hand)) == [("opened", 60)]


def test_cooldown_elapsed_during_a_long_gap_allows_a_new_call() -> None:
    eng = engine(calls(cooldown_s=60))
    hand = TrackObs(track_id=1, bbox=INSIDE, raised_hand=True)
    run(eng, 0, 0, hand)
    run(eng, 1, 1, GUEST)
    assert states(run(eng, 200, 200, hand)) == [("opened", 200)]


# -- objects -------------------------------------------------------------------------


def glass(ts: float) -> Frame:
    return Frame(ts=ts, objects=(ObjectObs("wine glass", GLASS_BOX),))


def seconds(start: float, end: float, step: float = 0.5) -> list[float]:
    n = round((end - start) / step)
    return [start + i * step for i in range(n)]


def play(eng: SituationEngine, frames: list[Frame]) -> list[AlertEvent]:
    return [ev for f in frames for ev in eng.step(f)]


def test_gap_does_not_make_the_glass_disappear() -> None:
    eng = engine(GONE)
    events = play(eng, [glass(ts) for ts in seconds(0, 20)])
    # After the gap the detector misses the glass for less than the confirm window.
    events += play(eng, [Frame(ts=ts) for ts in seconds(20 + GAP, 20 + GAP + GONE_CONFIRM_S - 1)])
    events += play(eng, [glass(ts) for ts in seconds(20 + GAP + GONE_CONFIRM_S - 1, 80)])
    assert events == []


def test_glass_really_gone_after_gap_fires_after_the_confirm_window() -> None:
    eng = engine(GONE)
    play(eng, [glass(ts) for ts in seconds(0, 20)])
    events = play(eng, [Frame(ts=ts) for ts in seconds(20 + GAP, 80)])
    assert [e.state for e in events] == ["opened"]
    assert events[0].at.timestamp() >= 20 + GAP + GONE_CONFIRM_S - 0.5
