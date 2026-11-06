"""Situation engine: rules x zones over time -> alert lifecycle events.

Every enabled rule for this camera is evaluated on every zone carrying its `zone_tag`.
An alert opens when all conditions hold (and `cooldown_s` has passed since the last
opening for that rule and zone) and closes when they stop holding.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from aivee_contracts.events import AlertEvent
from aivee_contracts.geometry import Zone
from aivee_contracts.rules import Condition, Rule

from aivee_edge.domain.observation import Frame
from aivee_edge.domain.zone_state import ZoneState

AlertKey = tuple[str, str]  # (rule_id, zone_id)


def utc_from_timestamp(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=UTC)


def _at_least(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def holds(cond: Condition, state: ZoneState, now: float) -> bool:
    match cond.kind:
        case "present":
            return _at_least(state.present_for(cond.role, now), cond.min_duration_s)
        case "absent":
            return _at_least(state.absent_for(cond.role, now), cond.min_duration_s)
        case "count":
            return state.count(cond.role) >= cond.min_count
        case "pose":
            return cond.pose == "raised_hand" and state.raised_hand(cond.role)
        case "objects_unattended":
            return _at_least(state.unattended_for(cond.objects, now), cond.min_duration_s)


def _duration_ro(seconds: int) -> str:
    return f"{seconds // 60} min" if seconds >= 60 else f"{seconds} s"


def summary_ro(rule: Rule, state: ZoneState) -> str:
    """Short Romanian text, chosen by the most specific condition in the rule."""
    by_kind = {c.kind: c for c in rule.all_of}
    name = state.zone.name
    if "pose" in by_kind:
        return f"{name}: un client cheamă"
    if c := by_kind.get("objects_unattended"):
        return f"{name}: nedebarasată de {_duration_ro(c.min_duration_s)}"
    if c := by_kind.get("count"):
        return f"{name}: {state.count(c.role)} persoane așteaptă"
    if c := by_kind.get("absent"):
        return f"{name}: neservită de {_duration_ro(c.min_duration_s)}"
    c = by_kind["present"]
    return f"{name}: ocupată de {_duration_ro(c.min_duration_s)}"


class SituationEngine:
    def __init__(
        self,
        rules: list[Rule],
        zones: list[Zone],
        id_factory: Callable[[], str],
        camera_id: str,
        to_datetime: Callable[[float], datetime] = utc_from_timestamp,
        grace_s: float = 0.0,
    ) -> None:
        self._states = {z.id: ZoneState(z, grace_s=grace_s) for z in zones}
        self._id_factory = id_factory
        self._camera_id = camera_id
        self._to_datetime = to_datetime
        self._open: set[AlertKey] = set()
        self._last_opened: dict[AlertKey, float] = {}
        self._rules: list[Rule] = []
        self.update_rules(rules)

    def update_rules(self, rules: list[Rule]) -> None:
        """Replace the active rule set; alerts of removed rules close on the next step."""
        self._rules = [r for r in rules if r.enabled and r.camera_id == self._camera_id]

    def step(self, frame: Frame) -> list[AlertEvent]:
        now = frame.ts
        for state in self._states.values():
            state.update(frame)

        events: list[AlertEvent] = []
        active: set[AlertKey] = set()
        for rule in self._rules:
            for state in self._states.values():
                if state.zone.tag != rule.zone_tag:
                    continue
                key = (rule.id, state.zone.id)
                active.add(key)
                ok = all(holds(c, state, now) for c in rule.all_of)
                if ok and key not in self._open:
                    last = self._last_opened.get(key)
                    if last is None or now - last >= rule.cooldown_s:
                        self._open.add(key)
                        self._last_opened[key] = now
                        events.append(self._event(key, "opened", now, summary_ro(rule, state)))
                elif not ok and key in self._open:
                    events.append(self._close(key, now))

        for key in sorted(self._open - active):
            events.append(self._close(key, now))
        return events

    def _close(self, key: AlertKey, now: float) -> AlertEvent:
        self._open.discard(key)
        return self._event(key, "closed", now, f"{self._states[key[1]].zone.name}: rezolvat")

    def _event(
        self, key: AlertKey, state: Literal["opened", "closed"], now: float, summary: str
    ) -> AlertEvent:
        rule_id, zone_id = key
        return AlertEvent(
            event_id=self._id_factory(),
            rule_id=rule_id,
            camera_id=self._camera_id,
            zone_id=zone_id,
            state=state,
            at=self._to_datetime(now),
            summary_ro=summary,
        )
