"""Match the alerts the edge produced on a clip to the clip's labels (pure, no IO).

See README.md for the label format. A produced alert is a hit when it opens inside an
expected window of the same kind and zone (widened by `tolerance_s` on both sides); each
expected window takes at most one hit, later alerts inside it are `repeats` (re-opened
after cooldown) and count neither for nor against. Any other alert is a false alert when
the clip is fully labelled, or when it opens inside a `quiet` segment otherwise.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from aivee_contracts.rules import Rule

# Condition kind -> alert kind, most specific first (same order as the edge's summary_ro).
KIND_BY_CONDITION: tuple[tuple[str, str], ...] = (
    ("object_gone", "object_gone"),
    ("visual", "visual"),
    ("object_present", "object_present"),
    ("pose", "raised_hand"),
    ("objects_unattended", "not_cleared"),
    ("count", "queue"),
    ("absent", "unattended"),
    ("present", "present"),
)
KINDS = tuple(kind for _, kind in KIND_BY_CONDITION)


def rule_kind(rule: Rule) -> str:
    """The alert kind a rule produces, from its most specific condition."""
    kinds = {c.kind for c in rule.all_of}
    return next(kind for cond, kind in KIND_BY_CONDITION if cond in kinds)


@dataclass(frozen=True)
class Expected:
    kind: str
    zone: str | None
    """Zone id; None matches any zone."""
    t_start: float
    t_end: float


@dataclass(frozen=True)
class Segment:
    t_start: float
    t_end: float

    def contains(self, t: float) -> bool:
        return self.t_start <= t <= self.t_end


@dataclass(frozen=True)
class Produced:
    kind: str
    zone: str
    t: float
    """Clip seconds at which the alert opened."""


@dataclass(frozen=True)
class ClipLabels:
    expected: tuple[Expected, ...] = ()
    quiet: tuple[Segment, ...] = ()
    fully_labelled: bool = True
    tolerance_s: float = 5.0

    @staticmethod
    def from_json(data: Mapping[str, Any]) -> ClipLabels:
        for e in data.get("expected", []):
            if e["kind"] not in KINDS:
                raise ValueError(f"unknown kind {e['kind']!r}; one of {', '.join(KINDS)}")
        return ClipLabels(
            expected=tuple(
                Expected(e["kind"], e.get("zone"), float(e["t_start"]), float(e["t_end"]))
                for e in data.get("expected", [])
            ),
            quiet=tuple(
                Segment(float(q["t_start"]), float(q["t_end"])) for q in data.get("quiet", [])
            ),
            fully_labelled=bool(data.get("fully_labelled", True)),
            tolerance_s=float(data.get("tolerance_s", 5.0)),
        )


@dataclass
class ClipResult:
    duration_s: float
    labelled_s: float
    hits: list[tuple[Expected, Produced]] = field(default_factory=list)
    misses: list[Expected] = field(default_factory=list)
    false_alerts: list[Produced] = field(default_factory=list)
    repeats: list[Produced] = field(default_factory=list)
    unjudged: list[Produced] = field(default_factory=list)
    """Unmatched alerts outside the quiet segments of a partly labelled clip."""


def _fits(e: Expected, p: Produced, tolerance_s: float) -> bool:
    return (
        e.kind == p.kind
        and (e.zone is None or e.zone == p.zone)
        and e.t_start - tolerance_s <= p.t <= e.t_end + tolerance_s
    )


def match(labels: ClipLabels, produced: Iterable[Produced], duration_s: float) -> ClipResult:
    """Judge one clip's produced alerts against its labels."""
    covered = sum(max(0.0, min(q.t_end, duration_s) - max(q.t_start, 0.0)) for q in labels.quiet)
    labelled_s = duration_s if labels.fully_labelled else covered
    result = ClipResult(duration_s=duration_s, labelled_s=labelled_s)
    hit: dict[int, Produced] = {}
    for p in sorted(produced, key=lambda a: a.t):
        fits = [i for i, e in enumerate(labels.expected) if _fits(e, p, labels.tolerance_s)]
        free = [i for i in fits if i not in hit]
        if free:
            hit[free[0]] = p
        elif fits:
            result.repeats.append(p)
        elif labels.fully_labelled or any(q.contains(p.t) for q in labels.quiet):
            result.false_alerts.append(p)
        else:
            result.unjudged.append(p)
    for i, e in enumerate(labels.expected):
        if i in hit:
            result.hits.append((e, hit[i]))
        else:
            result.misses.append(e)
    return result


@dataclass
class KindScore:
    expected: int = 0
    hits: int = 0
    false_alerts: int = 0

    @property
    def recall(self) -> float | None:
        return self.hits / self.expected if self.expected else None


@dataclass
class Summary:
    clips: int
    labelled_s: float
    by_kind: dict[str, KindScore]

    @property
    def false_alerts(self) -> int:
        return sum(k.false_alerts for k in self.by_kind.values())

    def false_per_hour(self, kind: str | None = None) -> float | None:
        if self.labelled_s <= 0:
            return None
        n = self.false_alerts if kind is None else self.by_kind[kind].false_alerts
        return n / (self.labelled_s / 3600)


def summarise(results: Sequence[ClipResult]) -> Summary:
    """Recall per kind and false alerts per labelled hour over all clips."""
    by_kind: dict[str, KindScore] = {}
    for r in results:
        for e in [e for e, _ in r.hits] + r.misses:
            by_kind.setdefault(e.kind, KindScore()).expected += 1
        for e, _ in r.hits:
            by_kind[e.kind].hits += 1
        for p in r.false_alerts:
            by_kind.setdefault(p.kind, KindScore()).false_alerts += 1
    return Summary(len(results), sum(r.labelled_s for r in results), dict(sorted(by_kind.items())))


def report(summary: Summary) -> str:
    """Plain-text table: one row per kind, then the totals."""
    hours = summary.labelled_s / 3600
    lines = [
        f"clips: {summary.clips}, labelled: {hours:.2f} h",
        f"{'kind':<16}{'expected':>9}{'hits':>6}{'recall':>8}{'false':>7}{'false/h':>9}",
    ]
    for kind, k in summary.by_kind.items():
        recall = "-" if k.recall is None else f"{k.recall:.0%}"
        fph = summary.false_per_hour(kind)
        lines.append(
            f"{kind:<16}{k.expected:>9}{k.hits:>6}{recall:>8}{k.false_alerts:>7}"
            f"{'-' if fph is None else f'{fph:.1f}':>9}"
        )
    total = summary.false_per_hour()
    per_hour = "-" if total is None else f"{total:.1f}"
    lines.append(f"false alerts: {summary.false_alerts}, per hour: {per_hour}")
    return "\n".join(lines)
