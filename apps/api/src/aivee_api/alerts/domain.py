"""Alert lifecycle as the owner sees it — pure: no DB, no FastAPI.

    opened (edge) → acknowledged (user, "Merg eu") → arrived (edge) → closed (edge)

`arrived` may come without `acknowledged` ("fără preluare").

- wait     = arrived (or closed) - opened
- reaction = acknowledged - opened
- travel   = arrived - acknowledged (only when the ack came first)
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

AlertState = Literal["opened", "acknowledged", "arrived", "closed"]


def _seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None or end < start:
        return None
    return round((end - start).total_seconds(), 1)


@dataclass(frozen=True)
class Lifecycle:
    opened_at: datetime
    acknowledged_at: datetime | None = None
    arrived_at: datetime | None = None
    closed_at: datetime | None = None

    @property
    def state(self) -> AlertState:
        if self.closed_at is not None:
            return "closed"
        if self.arrived_at is not None:
            return "arrived"
        if self.acknowledged_at is not None:
            return "acknowledged"
        return "opened"

    @property
    def last_change(self) -> datetime:
        stamps = (self.opened_at, self.acknowledged_at, self.arrived_at, self.closed_at)
        return max(t for t in stamps if t is not None)

    @property
    def wait_s(self) -> float | None:
        return _seconds(self.opened_at, self.arrived_at or self.closed_at)

    @property
    def reaction_s(self) -> float | None:
        return _seconds(self.opened_at, self.acknowledged_at)

    @property
    def travel_s(self) -> float | None:
        return _seconds(self.acknowledged_at, self.arrived_at)

    @property
    def unacknowledged_arrival(self) -> bool:
        """Staff arrived although nobody pressed "Merg eu" first."""
        return self.arrived_at is not None and (
            self.acknowledged_at is None or self.acknowledged_at > self.arrived_at
        )


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear interpolation between closest ranks (numpy's default)."""
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo), 1)


@dataclass(frozen=True)
class Measure:
    count: int
    median_s: float | None
    p90_s: float | None

    @classmethod
    def of(cls, values: Iterable[float | None]) -> "Measure":
        present = [v for v in values if v is not None]
        return cls(len(present), percentile(present, 0.5), percentile(present, 0.9))


@dataclass(frozen=True)
class ServiceStats:
    alerts: int
    unacknowledged_arrivals: int
    wait: Measure
    reaction: Measure
    travel: Measure


def service_stats(lives: Sequence[Lifecycle]) -> ServiceStats:
    return ServiceStats(
        alerts=len(lives),
        unacknowledged_arrivals=sum(1 for life in lives if life.unacknowledged_arrival),
        wait=Measure.of(life.wait_s for life in lives),
        reaction=Measure.of(life.reaction_s for life in lives),
        travel=Measure.of(life.travel_s for life in lives),
    )


def duration_ro(seconds: float) -> str:
    """ "2 min 10 s", "45 s", "3 min"."""
    total = round(seconds)
    minutes, rest = divmod(total, 60)
    if minutes == 0:
        return f"{rest} s"
    return f"{minutes} min" if rest == 0 else f"{minutes} min {rest} s"


def zone_name_from_summary(summary_ro: str) -> str | None:
    """Edge summaries start with the zone's name: "Masa 4: neservită de 2 min"."""
    name, sep, _ = summary_ro.partition(":")
    return name.strip() or None if sep else None
