"""CLIP visual scorer ports with a fake model (tools/visual_probe.py runs the real one)."""

import threading
import time
from collections.abc import Sequence
from typing import Any

import numpy as np
from aivee_edge.adapters.clip_visual import BackgroundVisualScorer, InlineVisualScorer, crop_box
from aivee_edge.adapters.yolo import DEFAULT_CLASSES, with_extra
from aivee_edge.domain.visual import VisualJob, VisualSample

NAMES = {0: "person", 21: "bear", 16: "dog", 41: "cup", 39: "bottle", 40: "wine glass"}
NAMES |= {42: "fork", 43: "knife", 44: "spoon", 45: "bowl"}

JOB = VisualJob(("fire", "anywhere", 0), None, ("fire",), ("room",))


class FakeClip:
    """Stands in for ClipVisualScorer: score = mean pixel / 255."""

    instances = 0

    def __init__(self, gate: threading.Event | None = None, fail: bool = False) -> None:
        FakeClip.instances += 1
        self.gate = gate
        self.fail = fail
        self.prepared: list[str] = []

    def prepare(self, prompts: Sequence[str]) -> None:
        self.prepared += list(prompts)

    def score_jobs(self, ts: float, image: Any, jobs: Sequence[VisualJob]) -> list[VisualSample]:
        if self.gate is not None:
            self.gate.wait(2)
        if self.fail:
            raise RuntimeError("boom")
        return [VisualSample(ts, j.key, float(np.mean(image)) / 255) for j in jobs]


def wait_for(cond: Any, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.005)


def test_crop_box_cuts_the_normalised_box_and_falls_back_to_the_frame() -> None:
    img = np.zeros((100, 200, 3), dtype=np.uint8)
    assert crop_box(img, (0.25, 0.5, 0.75, 1.0)).shape == (50, 100, 3)
    assert crop_box(img, None) is img
    assert crop_box(img, (0.5, 0.5, 0.51, 0.51)) is img  # too small to score


def test_inline_scorer_loads_lazily_and_scores_inside_submit() -> None:
    made: list[FakeClip] = []

    def factory() -> Any:
        made.append(FakeClip())
        return made[-1]

    scorer = InlineVisualScorer(factory)
    assert made == []
    assert scorer.submit(1.0, np.full((4, 4, 3), 255, np.uint8), [JOB])
    assert scorer.collect() == [VisualSample(1.0, JOB.key, 1.0)]
    assert scorer.collect() == [] and len(made) == 1


def test_background_scorer_keeps_one_frame_in_flight() -> None:
    gate = threading.Event()
    clip = FakeClip(gate)
    scorer = BackgroundVisualScorer(lambda: clip)  # type: ignore[arg-type, return-value]
    img = np.zeros((4, 4, 3), np.uint8)
    assert scorer.submit(1.0, img, [JOB])
    assert not scorer.submit(1.5, img, [JOB])  # still busy with 1.0
    assert scorer.collect() == []
    gate.set()
    wait_for(lambda: scorer.submit(2.0, img, [JOB]))
    wait_for(lambda: len(scorer._done) == 2)
    assert [s.ts for s in scorer.collect()] == [1.0, 2.0]
    assert scorer.last_ms is not None
    scorer.close()


def test_background_scorer_prepares_prompts_and_survives_a_failure() -> None:
    clip = FakeClip(fail=True)
    scorer = BackgroundVisualScorer(lambda: clip)  # type: ignore[arg-type, return-value]
    scorer.prepare(["a photo of fire"])
    img = np.zeros((4, 4, 3), np.uint8)
    assert scorer.submit(1.0, img, [JOB])
    wait_for(lambda: scorer.submit(2.0, img, [JOB]))  # free again after the failure
    assert clip.prepared == ["a photo of fire"] and scorer.collect() == []
    scorer.close()


def test_detector_adds_rule_classes_and_reports_unknown_ones() -> None:
    ids, unknown = with_extra(NAMES, DEFAULT_CLASSES, ["bear", "dog", "cup", "unicorn"])
    assert {NAMES[i] for i in ids} == set(DEFAULT_CLASSES) | {"bear", "dog"}
    assert len(ids) == len(set(ids)) and unknown == ["unicorn"]
