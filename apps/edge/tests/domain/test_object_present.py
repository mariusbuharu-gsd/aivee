"""`object_present` with fake detections, in a drawn zone and on the whole frame."""

from collections.abc import Iterator
from itertools import count

from aivee_contracts.geometry import Zone
from aivee_contracts.rules import ANYWHERE_TAG, Action, Condition, Rule
from aivee_edge.domain.engine import SituationEngine
from aivee_edge.domain.observation import BBox, Frame, ObjectObs
from aivee_edge.domain.visual import whole_frame_zone

CAM = "cam1"
TERRACE = Zone(
    id="z1", name="Terasă", tag="terrace", polygon=[(0.0, 0.5), (0.5, 0.5), (0.5, 1.0), (0.0, 1.0)]
)
FRAME = whole_frame_zone("Terasă")
IN_TERRACE: BBox = (0.1, 0.6, 0.3, 0.9)  # base (0.2, 0.9) is inside
OUTSIDE: BBox = (0.6, 0.1, 0.8, 0.3)
BOTTOM_EDGE: BBox = (0.7, 0.6, 0.95, 1.0)  # touches the image's bottom edge


def rule(tag: str, objects: list[str], min_s: int = 2, cooldown_s: int = 0) -> Rule:
    return Rule(
        id="r",
        camera_id=CAM,
        name="Urs",
        prompt_ro="anunță-mă dacă vine un urs",
        zone_tag=tag,
        all_of=[Condition(kind="object_present", objects=objects, min_duration_s=min_s)],
        action=Action(type="telegram"),
        cooldown_s=cooldown_s,
    )


def engine(r: Rule, grace_s: float = 1.0) -> SituationEngine:
    ids: Iterator[int] = count(1)
    return SituationEngine(
        [r], [TERRACE, FRAME], id_factory=lambda: f"ev{next(ids)}", camera_id=CAM, grace_s=grace_s
    )


def frame(ts: float, *objs: tuple[str, BBox]) -> Frame:
    return Frame(ts=ts, objects=tuple(ObjectObs(label, box) for label, box in objs))


def test_bear_in_the_zone_for_min_duration_opens_with_its_name() -> None:
    eng = engine(rule("terrace", ["bear"]))
    events = [e for k in range(25) for e in eng.step(frame(k / 10, ("bear", IN_TERRACE)))]
    assert [(e.state, e.at.timestamp(), e.summary_ro) for e in events] == [
        ("opened", 2.0, "Terasă: a apărut un urs")
    ]


def test_object_outside_the_zone_or_of_another_class_does_not_count() -> None:
    eng = engine(rule("terrace", ["bear"], min_s=0))
    for k in range(30):
        assert eng.step(frame(k / 10, ("bear", OUTSIDE), ("dog", IN_TERRACE))) == []


def test_closes_after_grace_once_the_object_is_gone() -> None:
    eng = engine(rule("terrace", ["dog"], min_s=0), grace_s=1.0)
    assert [e.state for e in eng.step(frame(0.0, ("dog", IN_TERRACE)))] == ["opened"]
    assert eng.step(frame(0.5)) == []
    assert eng.step(frame(1.0)) == []  # missing for 1.0 s: still within grace
    assert [e.state for e in eng.step(frame(1.1))] == ["closed"]


def test_a_flicker_within_grace_keeps_the_timer() -> None:
    eng = engine(rule("terrace", ["knife"], min_s=2), grace_s=1.0)
    events = []
    for k in range(25):
        ts = k / 10
        objs = () if 0.8 <= ts <= 1.2 else (("knife", IN_TERRACE),)
        events += eng.step(frame(ts, *objs))
    assert [(e.state, e.at.timestamp()) for e in events] == [("opened", 2.0)]


def test_anywhere_rule_sees_objects_all_over_the_image_edges_included() -> None:
    eng = engine(rule(ANYWHERE_TAG, ["bear", "dog"], min_s=0))
    opened = eng.step(frame(0.0, ("dog", BOTTOM_EDGE)))
    assert [(e.state, e.zone_id, e.summary_ro) for e in opened] == [
        ("opened", ANYWHERE_TAG, "Terasă: a apărut un câine")
    ]


def test_the_longest_present_class_is_named() -> None:
    eng = engine(rule(ANYWHERE_TAG, ["dog", "bear"], min_s=1))
    eng.step(frame(0.0, ("bear", OUTSIDE)))
    opened = eng.step(frame(1.0, ("bear", OUTSIDE), ("dog", IN_TERRACE)))
    assert [e.summary_ro for e in opened] == ["Terasă: a apărut un urs"]
