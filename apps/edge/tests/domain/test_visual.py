"""`visual` conditions through the engine, with a fake scorer (no CLIP)."""

from collections.abc import Callable, Iterator, Sequence
from itertools import count

import pytest
from aivee_contracts.geometry import Zone
from aivee_contracts.rules import ANYWHERE_TAG, Action, Condition, Rule
from aivee_edge.domain.engine import SituationEngine
from aivee_edge.domain.observation import Frame
from aivee_edge.domain.ports import Image
from aivee_edge.domain.visual import (
    VisualJob,
    VisualSample,
    VisualWatch,
    positive_share,
    whole_frame_zone,
    with_whole_frame,
    zone_box,
)

CAM = "cam1"
ROOM = Zone(id="z1", name="Sala", tag="room", polygon=[(0.1, 0.2), (0.5, 0.2), (0.3, 0.6)])
TABLE = Zone(id="t1", name="Masa 1", tag="table", polygon=[(0.6, 0.6), (0.9, 0.6), (0.9, 0.9)])
FRAME = whole_frame_zone("Sala principală")


def visual(min_s: int = 3, threshold: float = 0.6, crop: str | None = None) -> Condition:
    return Condition.model_validate(
        {
            "kind": "visual",
            "positive": ["a photo of fire", "flames"],
            "negative": ["a normal restaurant room"],
            "min_duration_s": min_s,
            "threshold": threshold,
            "crop": crop,
            "label_ro": "foc",
        }
    )


def rule(tag: str = ANYWHERE_TAG, *conds: Condition, rule_id: str = "fire") -> Rule:
    return Rule(
        id=rule_id,
        camera_id=CAM,
        name="Foc",
        prompt_ro="dacă e foc",
        zone_tag=tag,
        all_of=list(conds) or [visual()],
        action=Action(type="telegram"),
        cooldown_s=0,
    )


class FakeScorer:
    """Scores inline from `score(ts)`; remembers every call."""

    def __init__(self, score: Callable[[float], float] = lambda ts: 0.0) -> None:
        self.score = score
        self.prepared: list[list[str]] = []
        self.submits: list[tuple[float, list[VisualJob]]] = []
        self.collects = 0
        self.busy = False
        self._done: list[VisualSample] = []

    def prepare(self, prompts: Sequence[str]) -> None:
        self.prepared.append(list(prompts))

    def submit(self, ts: float, image: Image, jobs: Sequence[VisualJob]) -> bool:
        if self.busy:
            return False
        self.submits.append((ts, list(jobs)))
        self._done += [VisualSample(ts, j.key, self.score(ts)) for j in jobs]
        return True

    def collect(self) -> list[VisualSample]:
        self.collects += 1
        done, self._done = self._done, []
        return done


def engine(
    *rules: Rule,
    scorer: FakeScorer,
    zones: Sequence[Zone] = (ROOM, TABLE, FRAME),
    grace_s: float = 0.0,
    hz: float = 2.0,
) -> SituationEngine:
    ids: Iterator[int] = count(1)
    return SituationEngine(
        list(rules),
        list(zones),
        id_factory=lambda: f"ev{next(ids)}",
        camera_id=CAM,
        grace_s=grace_s,
        visual=scorer,
        visual_hz=hz,
    )


IMG = object()


def run(eng: SituationEngine, start: float, end: float, fps: float = 10.0) -> list[str]:
    """Step at `fps` from `start` (inclusive) to `end` (exclusive); 'state@ts' per event."""
    out: list[str] = []
    n = round((end - start) * fps)
    for k in range(n):
        ts = round(start + k / fps, 3)
        out += [f"{e.state}@{ts}" for e in eng.step(Frame(ts=ts), IMG)]
    return out


def test_positive_share_is_the_softmax_mass_of_the_positive_prompts() -> None:
    assert positive_share([1.0, 1.0], 1) == pytest.approx(0.5)
    assert positive_share([2.0, 2.0, 2.0, 2.0], 2) == pytest.approx(0.5)
    assert positive_share([30.0, 20.0], 1) == pytest.approx(1.0, abs=1e-4)
    assert positive_share([20.0, 30.0], 1) == pytest.approx(0.0, abs=1e-4)
    assert positive_share([], 1) == 0.0


def test_sustained_score_above_threshold_opens_once_after_min_duration() -> None:
    scorer = FakeScorer(lambda ts: 0.9 if ts >= 1.0 else 0.1)
    eng = engine(rule(), scorer=scorer)
    events = run(eng, 0.0, 6.0)
    assert events == ["opened@4.0"]  # first sample above at 1.0, held 3 s
    opened = eng.step(Frame(ts=6.0), IMG)
    assert opened == []


def test_opened_event_names_the_camera_and_what_was_seen() -> None:
    eng = engine(rule(), scorer=FakeScorer(lambda ts: 0.9))
    events = [e for k in range(50) for e in eng.step(Frame(ts=k / 10), IMG)]
    assert [(e.state, e.zone_id, e.summary_ro) for e in events] == [
        ("opened", ANYWHERE_TAG, "Sala principală: posibil foc")
    ]


def test_drop_below_threshold_closes_after_grace() -> None:
    scorer = FakeScorer(lambda ts: 0.9 if ts < 5.0 else 0.2)
    eng = engine(rule(), scorer=scorer, grace_s=2.0)
    events = run(eng, 0.0, 10.0)
    # Last sample above at 4.5; below samples at 5.0…6.5 are within grace; 7.0 is not.
    assert events == ["opened@3.0", "closed@7.0"]


def test_a_single_low_sample_within_grace_does_not_reset_the_run() -> None:
    scorer = FakeScorer(lambda ts: 0.2 if 1.4 < ts < 1.6 else 0.9)
    eng = engine(rule(), scorer=scorer, grace_s=1.0)
    assert run(eng, 0.0, 4.0) == ["opened@3.0"]


def test_without_grace_a_low_sample_restarts_min_duration() -> None:
    scorer = FakeScorer(lambda ts: 0.2 if 1.4 < ts < 1.6 else 0.9)
    eng = engine(rule(), scorer=scorer, grace_s=0.0)
    assert run(eng, 0.0, 5.1) == ["opened@5.0"]  # low sample at 1.5, above again from 2.0


def test_scoring_is_throttled_to_visual_hz() -> None:
    scorer = FakeScorer(lambda ts: 0.0)
    eng = engine(rule(), scorer=scorer, hz=2.0)
    run(eng, 0.0, 3.0, fps=15.0)
    assert [round(ts, 2) for ts, _ in scorer.submits] == [0.0, 0.53, 1.07, 1.6, 2.13, 2.67]


def test_a_busy_scorer_is_retried_on_the_next_frame() -> None:
    scorer = FakeScorer(lambda ts: 0.0)
    scorer.busy = True
    eng = engine(rule(), scorer=scorer)
    eng.step(Frame(ts=0.0), IMG)
    scorer.busy = False
    eng.step(Frame(ts=0.1), IMG)
    assert [ts for ts, _ in scorer.submits] == [0.1]


def test_no_scorer_calls_without_a_visual_rule() -> None:
    scorer = FakeScorer(lambda ts: 0.9)
    present = Condition(kind="present", role="guest")
    disabled = rule().model_copy(update={"enabled": False})
    eng = engine(rule("table", present, rule_id="other"), disabled, scorer=scorer)
    run(eng, 0.0, 5.0)
    assert (scorer.submits, scorer.collects, scorer.prepared) == ([], 0, [])


def test_removing_the_visual_rule_stops_scoring_and_closes_its_alert() -> None:
    scorer = FakeScorer(lambda ts: 0.9)
    eng = engine(rule(ANYWHERE_TAG, visual(min_s=0)), scorer=scorer)
    assert run(eng, 0.0, 1.0) == ["opened@0.0"]
    eng.update_rules([])
    calls = len(scorer.submits)
    assert run(eng, 1.0, 3.0) == ["closed@1.0"]
    assert len(scorer.submits) == calls


def test_text_prompts_are_prepared_once_per_rule_load() -> None:
    scorer = FakeScorer()
    eng = engine(rule(), scorer=scorer)
    run(eng, 0.0, 3.0)
    assert scorer.prepared == [["a photo of fire", "flames", "a normal restaurant room"]]


def test_zone_crop_is_the_zone_box_and_frame_crop_or_anywhere_is_the_whole_image() -> None:
    scorer = FakeScorer()
    eng = engine(
        rule("room", visual(), rule_id="a"),
        rule("room", visual(crop="frame"), rule_id="b"),
        rule(ANYWHERE_TAG, visual(), rule_id="c"),
        scorer=scorer,
    )
    eng.step(Frame(ts=0.0), IMG)
    boxes = {j.key: j.box for j in scorer.submits[0][1]}
    assert boxes == {
        ("a", "z1", 0): pytest.approx((0.1, 0.2, 0.5, 0.6)),
        ("b", "z1", 0): None,
        ("c", ANYWHERE_TAG, 0): None,
    }
    assert zone_box(FRAME) is None


def test_visual_and_another_condition_must_hold_together() -> None:
    scorer = FakeScorer(lambda ts: 0.9)
    guest_here = Condition(kind="present", role="guest")
    eng = engine(rule("room", visual(min_s=0), guest_here), scorer=scorer)
    assert run(eng, 0.0, 2.0) == []  # nobody in the room


def test_without_a_scorer_visual_never_holds() -> None:
    eng = SituationEngine([rule()], [FRAME], id_factory=lambda: "e", camera_id=CAM)
    assert [e for k in range(50) for e in eng.step(Frame(ts=k / 10), IMG)] == []


def test_capture_gap_freezes_the_run() -> None:
    scorer = FakeScorer(lambda ts: 0.9)
    eng = SituationEngine(
        [rule(ANYWHERE_TAG, visual(min_s=3))],
        [FRAME],
        id_factory=lambda: "e",
        camera_id=CAM,
        grace_s=1.0,
        gap_s=2.0,
        visual=scorer,
    )
    for ts in (0.0, 0.5, 1.0):
        assert eng.step(Frame(ts=ts), IMG) == []
    # 30 s with no frames: not observed time, so 2 s more are needed after it.
    assert eng.step(Frame(ts=31.0), IMG) == []
    assert eng.step(Frame(ts=32.0), IMG) == []
    assert [e.state for e in eng.step(Frame(ts=33.0), IMG)] == ["opened"]


def test_threshold_edit_restarts_the_run_but_an_unrelated_reload_does_not() -> None:
    watch = VisualWatch(hz=2.0, grace_s=0.0)
    r = rule(ANYWHERE_TAG, visual(min_s=1))
    watch.configure([r], [FRAME])
    key = ("fire", ANYWHERE_TAG, 0)
    watch.observe(VisualSample(0.0, key, 0.9))
    watch.configure([r], [FRAME, ROOM])
    assert watch.holds(key, r.all_of[0], 1.0)
    edited = rule(ANYWHERE_TAG, visual(min_s=1, threshold=0.95))
    watch.configure([edited], [FRAME])
    assert not watch.holds(key, edited.all_of[0], 1.0)


def test_late_samples_older_than_the_last_one_are_ignored() -> None:
    watch = VisualWatch(hz=2.0, grace_s=0.0)
    r = rule(ANYWHERE_TAG, visual(min_s=0))
    watch.configure([r], [FRAME])
    key = ("fire", ANYWHERE_TAG, 0)
    watch.observe(VisualSample(2.0, key, 0.1))
    watch.observe(VisualSample(1.5, key, 0.9))
    assert not watch.holds(key, r.all_of[0], 2.0)


def test_whole_frame_pseudo_zone_is_added_only_when_a_rule_uses_it() -> None:
    present = Condition(kind="present", role="guest")
    assert with_whole_frame([ROOM], [rule("room", present)], "Cam") == [ROOM]
    zones = with_whole_frame([ROOM], [rule()], "Cam")
    assert [z.id for z in zones] == ["z1", ANYWHERE_TAG] and zones[1].name == "Cam"
    off = rule().model_copy(update={"enabled": False})
    assert with_whole_frame([ROOM], [off], "Cam") == [ROOM]
