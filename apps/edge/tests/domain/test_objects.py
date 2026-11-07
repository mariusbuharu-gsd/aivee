"""Object presence with hysteresis and the object_gone condition."""

from collections.abc import Iterator
from itertools import count

from aivee_contracts.events import AlertEvent
from aivee_contracts.geometry import Zone
from aivee_contracts.rules import Action, Condition, Rule
from aivee_edge.domain.engine import SituationEngine
from aivee_edge.domain.objects import GONE_CONFIRM_S, GONE_HOLD_S, ObjectPresence, object_ro
from aivee_edge.domain.observation import Frame, ObjectObs

CAM = "cam1"
TABLE = Zone(id="t1", name="Masa 1", tag="table", polygon=[(0, 0), (0.4, 0), (0.4, 0.4), (0, 0.4)])
GLASS_BOX = (0.1, 0.1, 0.15, 0.3)  # base (bottom-centre) inside the table
GLASS_BOX_2 = (0.2, 0.1, 0.25, 0.3)
OUTSIDE_BOX = (0.6, 0.6, 0.65, 0.8)


def gone_rule(min_s: int = 10, cooldown_s: int = 0) -> Rule:
    return Rule(
        id="gone",
        camera_id=CAM,
        name="Pahar dispărut",
        prompt_ro="Anunță-mă dacă dispare un pahar de pe masă",
        zone_tag="table",
        all_of=[Condition(kind="object_gone", objects=["wine glass", "cup"], min_duration_s=min_s)],
        action=Action(type="telegram"),
        cooldown_s=cooldown_s,
    )


def engine(rule: Rule) -> SituationEngine:
    ids: Iterator[int] = count(1)
    return SituationEngine([rule], [TABLE], id_factory=lambda: f"ev{next(ids)}", camera_id=CAM)


def frame(ts: float, *boxes: tuple[float, float, float, float], label: str = "wine glass") -> Frame:
    return Frame(ts=ts, objects=tuple(ObjectObs(label, b) for b in boxes))


def run(eng: SituationEngine, frames: list[Frame]) -> list[AlertEvent]:
    return [ev for f in frames for ev in eng.step(f)]


def seconds(start: float, end: float, step: float = 0.5) -> list[float]:
    n = round((end - start) / step)
    return [start + i * step for i in range(n)]


# -- ObjectPresence ------------------------------------------------------------------


def test_a_short_detection_gap_does_not_count_as_gone() -> None:
    p = ObjectPresence()
    for ts in seconds(0, 20):
        p.update(ts, {"cup": 1})
    for ts in seconds(20, 20 + GONE_CONFIRM_S - 0.5):
        p.update(ts, {})
    assert p.gone(["cup"], 10, 22.5) is None
    p.update(23.0, {"cup": 1})
    assert p.gone(["cup"], 10, 23.0) is None


def test_a_stable_disappearance_is_recorded_with_how_long_it_was_there() -> None:
    p = ObjectPresence()
    for ts in seconds(0, 20):
        p.update(ts, {"cup": 1})
    for ts in seconds(20, 25):
        p.update(ts, {})
    gone = p.gone(["cup"], 10, 24.5)
    assert gone is not None
    assert gone.label == "cup"
    assert gone.last_seen == 19.5
    assert gone.present_s == 19.5


def test_one_of_two_glasses_gone_counts_per_class() -> None:
    p = ObjectPresence()
    for ts in seconds(0, 20):
        p.update(ts, {"wine glass": 2})
    for ts in seconds(20, 25):
        p.update(ts, {"wine glass": 1})
    assert p.gone(["wine glass"], 10, 24.5) is not None


def test_an_object_seen_too_briefly_is_not_gone() -> None:
    p = ObjectPresence()
    for ts in seconds(0, 5):
        p.update(ts, {"cup": 1})
    for ts in seconds(5, 10):
        p.update(ts, {})
    assert p.gone(["cup"], 10, 9.5) is None


def test_all_in_view_is_false_while_an_object_is_missing() -> None:
    p = ObjectPresence()
    p.update(0.0, {"cup": 2})
    assert p.all_in_view()
    p.update(0.5, {"cup": 1})
    assert not p.all_in_view()
    p.update(1.0, {"cup": 2})
    assert p.all_in_view()


def test_romanian_names() -> None:
    assert object_ro("wine glass") == "paharul de vin"
    assert object_ro("zebra") == "un obiect (zebra)"


# -- engine --------------------------------------------------------------------------


def present(start: float, end: float, *boxes: tuple[float, float, float, float]) -> list[Frame]:
    return [frame(ts, *boxes) for ts in seconds(start, end)]


def test_flicker_does_not_fire() -> None:
    eng = engine(gone_rule())
    frames = present(0, 20, GLASS_BOX)
    # Drop the glass every other second for 2 s: never missing for the confirm window.
    for ts in seconds(20, 60):
        frames.append(frame(ts) if int(ts) % 4 in (0, 1) else frame(ts, GLASS_BOX))
    assert run(eng, frames) == []


def test_stable_disappearance_fires_once_then_closes_after_the_hold() -> None:
    eng = engine(gone_rule())
    events = run(eng, present(0, 20, GLASS_BOX))
    events += run(eng, [frame(ts) for ts in seconds(20, 20 + GONE_CONFIRM_S + GONE_HOLD_S + 5)])
    assert [e.state for e in events] == ["opened", "closed"]
    opened, closed = events
    assert opened.summary_ro == "Masa 1: a dispărut paharul de vin"
    assert opened.object_change is not None
    assert opened.object_change.objects == ["wine glass"]
    assert opened.at.timestamp() >= 19.5 + GONE_CONFIRM_S
    assert closed.at.timestamp() - opened.at.timestamp() >= GONE_HOLD_S - 1
    assert closed.object_change is None


def test_reappearance_closes_and_resets() -> None:
    eng = engine(gone_rule())
    events = run(eng, present(0, 20, GLASS_BOX))
    events += run(eng, [frame(ts) for ts in seconds(20, 25)])
    events += run(eng, present(25, 30, GLASS_BOX))
    assert [e.state for e in events] == ["opened", "closed"]
    # Back for only 5 s: a second disappearance is shorter than min_duration_s, no alert.
    events = run(eng, [frame(ts) for ts in seconds(30, 40)])
    assert events == []


def test_objects_outside_the_zone_and_other_classes_are_ignored() -> None:
    eng = engine(gone_rule())
    frames = [frame(ts, OUTSIDE_BOX) for ts in seconds(0, 20)]
    frames += [frame(ts, GLASS_BOX, label="bottle") for ts in seconds(20, 40)]
    frames += [frame(ts) for ts in seconds(40, 50)]
    assert run(eng, frames) == []


def test_one_of_two_glasses_taken_fires() -> None:
    eng = engine(gone_rule())
    events = run(eng, present(0, 20, GLASS_BOX, GLASS_BOX_2))
    events += run(eng, present(20, 25, GLASS_BOX))
    assert [e.state for e in events] == ["opened"]
