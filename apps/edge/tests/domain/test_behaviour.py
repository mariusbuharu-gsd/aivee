import math
from collections.abc import Iterator

import pytest
from aivee_edge.domain.behaviour import (
    BehaviourFeatures,
    Point,
    TrajectoryBuffer,
    behaviour_score,
    foot_point,
)
from aivee_edge.domain.observation import Frame, TrackObs


def _square(x: float, y: float, half: float = 0.1) -> list[Point]:
    return [(x - half, y - half), (x + half, y - half), (x + half, y + half), (x - half, y + half)]


TABLES = {
    "t1": _square(0.2, 0.2),
    "t2": _square(0.8, 0.2),
    "t3": _square(0.2, 0.8),
    "t4": _square(0.8, 0.8),
}
KITCHEN = {"kitchen": [(0.4, 0.0), (0.6, 0.0), (0.6, 0.1), (0.4, 0.1)]}

HZ = 2.0
DT = 1 / HZ


def _walk(start: Point, end: Point, speed: float) -> Iterator[Point]:
    """Points along a straight line at `speed` units/s, sampled at HZ (excluding start)."""
    dist = math.dist(start, end)
    steps = max(1, round(dist / speed * HZ))
    for i in range(1, steps + 1):
        f = i / steps
        yield (start[0] + (end[0] - start[0]) * f, start[1] + (end[1] - start[1]) * f)


def _stay(at: Point, seconds: float, jitter: float = 0.003) -> Iterator[Point]:
    """Detector jitter around a fixed point."""
    for i in range(round(seconds * HZ)):
        sign = 1 if i % 2 else -1
        yield (at[0] + sign * jitter, at[1] - sign * jitter)


def _feed(buf: TrajectoryBuffer, track_id: int, points: Iterator[Point], t0: float = 0.0) -> float:
    ts = t0
    for p in points:
        buf.add(track_id, ts, p[0], p[1])
        ts += DT
    return ts


def _walker(duration: float) -> Iterator[Point]:
    """A waiter looping t1 → t2 → t4 → t3, pausing 5 s at each table."""
    route = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]
    pos = route[0]
    emitted = 0
    total = round(duration * HZ)
    while True:
        for nxt in route[1:] + route[:1]:
            for p in [*_walk(pos, nxt, 0.1), *_stay(nxt, 5, jitter=0.0)]:
                if emitted >= total:
                    return
                emitted += 1
                yield p
            pos = nxt


def _sitter(duration: float) -> Iterator[Point]:
    return _stay((0.2, 0.2), duration)


def _wanderer() -> Iterator[Point]:
    """A guest who sits at t1, walks to the toilet once (through t3) and comes back."""
    seat, toilet = (0.2, 0.2), (0.2, 0.98)
    yield from _stay(seat, 70)
    yield from _walk(seat, toilet, 0.1)
    yield from _stay(toilet, 20)
    yield from _walk(toilet, seat, 0.1)
    yield from _stay(seat, 70)


def _features(
    points: Iterator[Point], staff_zones: dict[str, list[Point]] | None = None
) -> BehaviourFeatures:
    buf = TrajectoryBuffer()
    _feed(buf, 1, points)
    return buf.features(1, TABLES, staff_zones or {})


def test_walker_between_tables_scores_high() -> None:
    f = _features(_walker(180))
    assert f.zones_visited == frozenset({"t1", "t2", "t3", "t4"})
    assert f.speed_per_min > 2.0
    assert f.stationary_ratio < 0.6
    assert behaviour_score(f) > 0.7


def test_seated_guest_scores_low() -> None:
    f = _features(_sitter(180))
    assert f.zones_visited == frozenset({"t1"})
    assert f.speed_per_min < 0.1
    assert f.stationary_ratio > 0.95
    assert behaviour_score(f) < 0.2


def test_guest_going_to_toilet_once_stays_below_staff_threshold() -> None:
    f = _features(_wanderer())
    assert f.zones_visited == frozenset({"t1", "t3"})
    assert behaviour_score(f) < 0.4


def test_short_history_is_not_confidently_staff() -> None:
    f = _features(_walker(10))
    assert f.duration_s < 20
    assert behaviour_score(f) < 0.2


def test_staff_zone_boosts_score() -> None:
    kitchen_trip = [*_stay((0.5, 0.05), 30), *_walk((0.5, 0.05), (0.2, 0.2), 0.1), *_sitter(60)]
    without = _features(iter(kitchen_trip))
    with_zone = _features(iter(kitchen_trip), KITCHEN)
    assert not without.in_staff_zone
    assert with_zone.in_staff_zone
    assert "kitchen" not in with_zone.zones_visited
    assert behaviour_score(with_zone) > behaviour_score(without)


def test_window_drops_old_samples() -> None:
    buf = TrajectoryBuffer(window_s=60)
    _feed(buf, 1, _sitter(120))
    samples = buf.samples(1)
    assert samples[-1].ts - samples[0].ts <= 60
    assert buf.features(1, TABLES).duration_s == pytest.approx(60, abs=DT)


def test_unknown_track_has_empty_features() -> None:
    f = TrajectoryBuffer().features(42, TABLES)
    assert f == BehaviourFeatures(
        duration_s=0.0,
        speed_per_min=0.0,
        zones_visited=frozenset(),
        stationary_ratio=1.0,
        in_staff_zone=False,
    )
    assert behaviour_score(f) == 0.0


def test_forget_removes_track() -> None:
    buf = TrajectoryBuffer()
    _feed(buf, 1, _sitter(5))
    buf.forget(1)
    buf.forget(99)  # unknown ids are fine
    assert buf.samples(1) == []


def test_observe_records_foot_points_of_frame_tracks() -> None:
    buf = TrajectoryBuffer()
    buf.observe(Frame(ts=1.0, tracks=(TrackObs(track_id=7, bbox=(0.1, 0.2, 0.3, 0.6)),)))
    (s,) = buf.samples(7)
    assert (s.ts, s.x, s.y) == (1.0, pytest.approx(0.2), 0.6)


def test_foot_point_is_bottom_centre() -> None:
    assert foot_point((0.2, 0.1, 0.4, 0.9)) == (pytest.approx(0.3), 0.9)


def test_score_is_clamped_to_unit_interval() -> None:
    f = BehaviourFeatures(
        duration_s=500,
        speed_per_min=99,
        zones_visited=frozenset(f"t{i}" for i in range(20)),
        stationary_ratio=0.0,
        in_staff_zone=True,
    )
    assert behaviour_score(f) == pytest.approx(1.0)
