"""`visual` conditions: zero-shot image checks ("e foc", "e apă pe jos"), pure state.

A `VisualScorer` (port, CLIP in the adapters) turns an image crop and two prompt lists into
the share of the softmax that falls on the positive prompts. Scoring is expensive (~0.1 s
on CPU), so `VisualWatch` asks for it at most `hz` times per second and only while at
least one enabled rule has a visual condition; between samples the last verdict stands.

Per (rule, zone, condition index) the watch keeps when the score went above the
condition's threshold. A sample below the threshold ends the run only once the last
sample above it is more than `grace_s` old, like a person missing from a zone for a
frame: one bad sample at 2 Hz does not reset a fire that has burned for 10 s, and an
alert closes about `grace_s` after the scene stops matching. `min_duration_s` counts
from the first sample above the threshold of the current run.

Samples carry the time of the frame they were taken from: a scorer running in the
background reports them a little later, and that is fine.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from aivee_contracts.geometry import Zone
from aivee_contracts.rules import ANYWHERE_TAG, Condition, Rule

from aivee_edge.domain.observation import BBox

VisualKey = tuple[str, str, int]
"""(rule_id, zone_id, index of the condition in `all_of`)."""

DEFAULT_VISUAL_HZ = 2.0

WHOLE_FRAME: list[tuple[float, float]] = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


def whole_frame_zone(name: str) -> Zone:
    """The pseudo-zone for rules tagged `anywhere`: the full image, named after the camera."""
    return Zone(id=ANYWHERE_TAG, name=name, tag=ANYWHERE_TAG, polygon=WHOLE_FRAME)


def with_whole_frame(zones: Sequence[Zone], rules: Iterable[Rule], name: str) -> list[Zone]:
    """`zones` plus the whole-frame pseudo-zone when an enabled rule asks for it."""
    out = [z for z in zones if z.id != ANYWHERE_TAG]
    if any(r.enabled and r.zone_tag == ANYWHERE_TAG for r in rules):
        out.append(whole_frame_zone(name))
    return out


def positive_share(logits: Sequence[float], n_positive: int) -> float:
    """Softmax over [positive…, negative…] logits; the summed share of the positives."""
    if not logits or n_positive <= 0:
        return 0.0
    top = max(logits)
    exps = [math.exp(v - top) for v in logits]
    return sum(exps[:n_positive]) / sum(exps)


def zone_box(zone: Zone) -> BBox | None:
    """Bounding box of a zone's polygon; None for the whole frame."""
    if zone.tag == ANYWHERE_TAG:
        return None
    xs = [p[0] for p in zone.polygon]
    ys = [p[1] for p in zone.polygon]
    return (min(xs), min(ys), max(xs), max(ys))


@dataclass(frozen=True)
class VisualJob:
    key: VisualKey
    box: BBox | None
    """Normalised crop (x1, y1, x2, y2); None scores the whole frame."""
    positive: tuple[str, ...]
    negative: tuple[str, ...]


@dataclass(frozen=True)
class VisualSample:
    ts: float
    key: VisualKey
    score: float


@dataclass
class _Run:
    threshold: float
    above_since: float | None = None
    last_above: float | None = None
    last_sample: float | None = None
    score: float | None = None


def visual_jobs(rules: Iterable[Rule], zones: Iterable[Zone]) -> list[VisualJob]:
    """One job per visual condition of every enabled rule, per zone carrying its tag."""
    zones = list(zones)
    jobs: list[VisualJob] = []
    for rule in rules:
        if not rule.enabled:
            continue
        for i, c in enumerate(rule.all_of):
            if c.kind != "visual":
                continue
            for z in zones:
                if z.tag != rule.zone_tag:
                    continue
                box = None if c.crop == "frame" else zone_box(z)
                jobs.append(
                    VisualJob((rule.id, z.id, i), box, tuple(c.positive), tuple(c.negative))
                )
    return jobs


def prompts_of(jobs: Iterable[VisualJob]) -> list[str]:
    """Every distinct prompt, in first-seen order (for the scorer's text cache)."""
    seen: dict[str, None] = {}
    for j in jobs:
        for p in (*j.positive, *j.negative):
            seen.setdefault(p, None)
    return list(seen)


class VisualWatch:
    def __init__(self, hz: float = DEFAULT_VISUAL_HZ, grace_s: float = 0.0) -> None:
        self.hz = hz
        self.grace_s = grace_s
        self._jobs: list[VisualJob] = []
        self._runs: dict[VisualKey, _Run] = {}
        self._last_submit: float | None = None

    @property
    def active(self) -> bool:
        """True while some enabled rule has a visual condition on an existing zone."""
        return bool(self._jobs) and self.hz > 0

    def configure(self, rules: Iterable[Rule], zones: Iterable[Zone]) -> list[str]:
        """New rules or zones. Runs of unchanged jobs are kept (a threshold edit restarts
        its run); returns the prompts the jobs need."""
        rules = list(rules)
        self._jobs = visual_jobs(rules, zones)
        thresholds = {
            (r.id, i): c.threshold
            for r in rules
            for i, c in enumerate(r.all_of)
            if c.kind == "visual"
        }
        runs: dict[VisualKey, _Run] = {}
        for job in self._jobs:
            threshold = thresholds[(job.key[0], job.key[2])]
            old = self._runs.get(job.key)
            runs[job.key] = (
                old if old is not None and old.threshold == threshold else _Run(threshold)
            )
        self._runs = runs
        return prompts_of(self._jobs)

    def jobs(self) -> list[VisualJob]:
        return list(self._jobs)

    def due(self, now: float) -> bool:
        if not self.active:
            return False
        last = self._last_submit
        return last is None or now - last + 1e-6 >= 1.0 / self.hz

    def submitted(self, now: float) -> None:
        self._last_submit = now

    def observe(self, sample: VisualSample) -> None:
        run = self._runs.get(sample.key)
        if run is None or (run.last_sample is not None and sample.ts < run.last_sample):
            return  # a removed job, or an older sample arriving late
        run.last_sample = sample.ts
        run.score = sample.score
        if sample.score >= run.threshold:
            if run.above_since is None:
                run.above_since = sample.ts
            run.last_above = sample.ts
        elif run.last_above is None or sample.ts - run.last_above > self.grace_s:
            run.above_since = None
            run.last_above = None

    def holds(self, key: VisualKey, cond: Condition, now: float) -> bool:
        run = self._runs.get(key)
        if run is None or run.above_since is None:
            return False
        return now - run.above_since >= cond.min_duration_s

    def score(self, key: VisualKey) -> float | None:
        """The latest sample's score (for logs), None before the first."""
        run = self._runs.get(key)
        return None if run is None else run.score

    def shift(self, dt: float) -> None:
        """A capture gap: freeze the runs and the throttle instead of letting them age."""
        if self._last_submit is not None:
            self._last_submit += dt
        for run in self._runs.values():
            if run.above_since is not None:
                run.above_since += dt
            if run.last_above is not None:
                run.last_above += dt
            if run.last_sample is not None:
                run.last_sample += dt
