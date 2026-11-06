"""Behaviour features of a tracked person: does this person move like staff?

Each track's foot point (bottom-centre of its box) is kept over a sliding window.
Waiters walk a lot and visit many tables; guests sit at one table and occasionally
go to the toilet. All distances are in normalised image units (the frame is 1 x 1).
"""

import itertools
import math
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from aivee_edge.domain.observation import BBox, Frame

Point = tuple[float, float]
Polygon = Sequence[Point]

WINDOW_S = 180.0
JITTER = 0.01
"""Displacements below this (normalised units) are detector noise, not movement."""
STATIONARY_SPEED = 0.02
"""Below this speed (units/s) a sample interval counts as standing still."""
STANDING_WINDOW_S = 3.0
"""Stance samples kept per track: a guest must stand for a while before it counts."""
STANDING_FULL_S = 2.0
"""Known-stance history needed for a full standing ratio; less scales it toward 0."""

# behaviour_score weights (sum to 1). Tables visited is the strongest staff signal, then
# how far the person walks; time spent moving and entering a staff zone add the rest.
W_ZONES = 0.40
W_SPEED = 0.30
W_MOVING = 0.15
W_STAFF_ZONE = 0.15
ZONES_FOR_FULL = 4
"""Distinct zones at which the zones term saturates; a single zone (own table) scores 0."""
SPEED_FOR_FULL = 2.5
"""Path length per minute at which the speed term saturates (~2.5 frame widths/min)."""
FULL_CONFIDENCE_S = 60.0
"""History needed for full confidence; shorter histories pull the score linearly toward 0."""


@dataclass(frozen=True)
class Sample:
    ts: float
    x: float
    y: float


@dataclass(frozen=True)
class BehaviourFeatures:
    duration_s: float
    """Time span covered by the samples in the window."""
    speed_per_min: float
    """De-jittered path length per minute, in normalised units."""
    zones_visited: frozenset[str]
    """Distinct non-staff zones (usually tables) the foot point entered."""
    stationary_ratio: float
    """Share of sample intervals slower than `STATIONARY_SPEED`; 1.0 with no movement data."""
    in_staff_zone: bool
    """The foot point was inside a staff zone (kitchen, bar) at least once."""
    standing_ratio: float | None = None
    """Share of the last `STANDING_WINDOW_S` with a known stance spent standing, scaled by
    coverage (known span / `STANDING_FULL_S`); None with no known stance."""


def foot_point(bbox: BBox) -> Point:
    x1, _, x2, y2 = bbox
    return ((x1 + x2) / 2, y2)


def _inside(p: Point, polygon: Polygon) -> bool:
    """Ray casting point-in-polygon."""
    x, y = p
    inside = False
    n = len(polygon)
    for i in range(n):
        (xa, ya), (xb, yb) = polygon[i], polygon[(i + 1) % n]
        if (ya > y) != (yb > y) and x < xa + (y - ya) * (xb - xa) / (yb - ya):
            inside = not inside
    return inside


class TrajectoryBuffer:
    """Per-track foot points over a sliding time window."""

    def __init__(self, window_s: float = WINDOW_S) -> None:
        self._window_s = window_s
        self._tracks: dict[int, deque[Sample]] = {}
        self._stances: dict[int, deque[tuple[float, bool]]] = {}

    def add(self, track_id: int, ts: float, x: float, y: float) -> None:
        samples = self._tracks.setdefault(track_id, deque())
        samples.append(Sample(ts, x, y))
        while samples and samples[0].ts < ts - self._window_s:
            samples.popleft()

    def add_stance(self, track_id: int, ts: float, standing: bool | None) -> None:
        stances = self._stances.setdefault(track_id, deque())
        if standing is not None:
            stances.append((ts, standing))
        while stances and stances[0][0] < ts - STANDING_WINDOW_S:
            stances.popleft()

    def observe(self, frame: Frame) -> None:
        for track in frame.tracks:
            x, y = foot_point(track.bbox)
            self.add(track.track_id, frame.ts, x, y)
            self.add_stance(track.track_id, frame.ts, track.standing)

    def forget(self, track_id: int) -> None:
        self._tracks.pop(track_id, None)
        self._stances.pop(track_id, None)

    def standing_ratio(self, track_id: int) -> float | None:
        stances = self._stances.get(track_id)
        if not stances:
            return None
        standing = sum(1 for _, s in stances if s) / len(stances)
        coverage = _clamp((stances[-1][0] - stances[0][0]) / STANDING_FULL_S)
        return standing * coverage

    def samples(self, track_id: int) -> list[Sample]:
        return list(self._tracks.get(track_id, ()))

    def features(
        self,
        track_id: int,
        zones: Mapping[str, Polygon],
        staff_zones: Mapping[str, Polygon] | None = None,
    ) -> BehaviourFeatures:
        samples = self.samples(track_id)
        staff_zones = staff_zones or {}
        standing = self.standing_ratio(track_id)
        if not samples:
            return BehaviourFeatures(0.0, 0.0, frozenset(), 1.0, False, standing)

        duration = samples[-1].ts - samples[0].ts
        points = [(s.x, s.y) for s in samples]

        path = 0.0
        anchor = points[0]
        for p in points[1:]:
            step = math.dist(anchor, p)
            if step >= JITTER:
                path += step
                anchor = p

        intervals = 0
        still = 0
        for a, b in itertools.pairwise(samples):
            dt = b.ts - a.ts
            if dt <= 0:
                continue
            intervals += 1
            if math.dist((a.x, a.y), (b.x, b.y)) / dt < STATIONARY_SPEED:
                still += 1

        visited = frozenset(
            zone_id
            for zone_id, polygon in zones.items()
            if zone_id not in staff_zones and any(_inside(p, polygon) for p in points)
        )
        in_staff = any(_inside(p, poly) for poly in staff_zones.values() for p in points)

        return BehaviourFeatures(
            duration_s=duration,
            speed_per_min=path / duration * 60 if duration > 0 else 0.0,
            zones_visited=visited,
            stationary_ratio=still / intervals if intervals else 1.0,
            in_staff_zone=in_staff,
            standing_ratio=standing,
        )


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def behaviour_score(features: BehaviourFeatures) -> float:
    """How staff-like the behaviour is, in [0, 1].

    raw = 0.40·zones + 0.30·speed + 0.15·(1 - stationary) + 0.15·staff_zone, where
    zones = (visited - 1) / 3 and speed = speed_per_min / 2.5, each clamped to [0, 1].
    The result is multiplied by confidence = duration / 60 s (clamped), so a person
    seen for under 20 s can never score above 0.33.
    """
    zones = _clamp((len(features.zones_visited) - 1) / (ZONES_FOR_FULL - 1))
    speed = _clamp(features.speed_per_min / SPEED_FOR_FULL)
    moving = 1.0 - features.stationary_ratio
    staff = 1.0 if features.in_staff_zone else 0.0
    raw = W_ZONES * zones + W_SPEED * speed + W_MOVING * moving + W_STAFF_ZONE * staff
    confidence = _clamp(features.duration_s / FULL_CONFIDENCE_S)
    return _clamp(raw * confidence)
