import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import yaml  # type: ignore[import-untyped]
from aivee_edge.adapters import yolo
from aivee_edge.adapters.yolo import (
    DEFAULT_CLASSES,
    class_ids_for,
    map_results,
    track_buffer_frames,
    tracker_config,
    with_extra,
    write_tracker_yaml,
)
from aivee_edge.domain.observation import ObjectObs, TrackObs

NAMES = {0: "person", 41: "cup", 39: "bottle", 60: "dining table"}


def test_yolo_output_is_mapped_to_domain() -> None:
    frame = map_results(
        boxes_xyxy=[[64, 48, 320, 480], [320, 240, 384, 288]],
        cls_ids=[0, 41],
        track_ids=[7, 8],
        confs=[0.9, 0.6],
        names=NAMES,
        width=640,
        height=480,
        ts=1.5,
    )
    assert frame.ts == 1.5
    assert frame.tracks == (TrackObs(track_id=7, bbox=(0.1, 0.1, 0.5, 1.0), confidence=0.9),)
    assert frame.tracks[0].role == "guest"
    assert frame.objects == (ObjectObs(label="cup", bbox=(0.5, 0.5, 0.6, 0.6), confidence=0.6),)


def test_boxes_are_clamped_to_unit_square() -> None:
    frame = map_results([[-10, -5, 700, 500]], [0], [1], [0.8], NAMES, 640, 480)
    assert frame.tracks[0].bbox == (0.0, 0.0, 1.0, 1.0)


def test_persons_without_track_id_are_skipped_objects_kept() -> None:
    frame = map_results(
        [[0, 0, 10, 10], [0, 0, 20, 20], [0, 0, 30, 30]],
        [0, 0, 39],
        [None, 3, None],
        [0.5, 0.5, 0.5],
        NAMES,
        100,
        100,
    )
    assert [t.track_id for t in frame.tracks] == [3]
    assert [o.label for o in frame.objects] == ["bottle"]


def test_no_track_ids_at_all() -> None:
    frame = map_results([[0, 0, 10, 10], [0, 0, 5, 5]], [0, 41], None, [0.9, 0.9], NAMES, 100, 100)
    assert frame.tracks == ()
    assert len(frame.objects) == 1


def test_empty_result() -> None:
    frame = map_results([], [], None, [], NAMES, 640, 480, ts=2.0)
    assert frame.tracks == () and frame.objects == () and frame.ts == 2.0


def test_frame_carries_the_image_aspect() -> None:
    assert map_results([], [], None, [], NAMES, 640, 480).aspect == pytest.approx(4 / 3)


def test_class_ids_for_excludes_dining_table_and_rejects_unknown() -> None:
    assert "dining table" not in DEFAULT_CLASSES
    assert class_ids_for(NAMES, ["person", "cup"]) == [0, 41]
    with pytest.raises(ValueError):
        class_ids_for(NAMES, ["unicorn"])


def test_knife_is_not_a_default_class_but_a_rule_can_still_ask_for_it() -> None:
    # Every restaurant table has knives: detecting them by default only feeds false alerts.
    names = {0: "person", 41: "cup", 42: "fork", 43: "knife", 44: "spoon"}
    assert "knife" not in DEFAULT_CLASSES
    assert {"person", "cup", "fork", "spoon"} <= set(DEFAULT_CLASSES)
    base = [c for c in DEFAULT_CLASSES if c in names.values()]
    ids, unknown = with_extra(names, base, ["knife"])
    assert 43 in ids and unknown == []


def test_low_score_objects_are_dropped_but_tracked_people_kept() -> None:
    # Low scores reach the tracker so it can keep people through occlusion; an object
    # still needs the rule-facing confidence.
    frame = map_results(
        [[0, 0, 10, 10], [0, 0, 20, 20], [0, 0, 30, 30]],
        [0, 41, 39],
        [1, 2, 3],
        [0.15, 0.2, 0.5],
        NAMES,
        100,
        100,
        min_object_conf=0.35,
    )
    assert [t.track_id for t in frame.tracks] == [1]
    assert [o.label for o in frame.objects] == ["bottle"]


@pytest.mark.parametrize(
    ("fps", "seconds", "frames"),
    [(10.0, 4.0, 40), (3.0, 4.0, 12), (25.0, 4.0, 100), (12.5, 3.0, 38), (0.2, 4.0, 1)],
)
def test_track_buffer_counts_frames_for_the_same_seconds_at_any_fps(
    fps: float, seconds: float, frames: int
) -> None:
    assert track_buffer_frames(fps, seconds) == frames


def test_track_buffer_needs_a_positive_fps() -> None:
    with pytest.raises(ValueError):
        track_buffer_frames(0.0, 4.0)


def test_tracker_config_keeps_low_scores_for_the_second_association() -> None:
    cfg = tracker_config(fps=5.0, lost_track_s=4.0, person_conf=0.35, low_conf=0.1)
    assert cfg["tracker_type"] == "bytetrack"
    assert (cfg["track_low_thresh"], cfg["track_high_thresh"], cfg["new_track_thresh"]) == (
        0.1,
        0.35,
        0.35,
    )
    assert cfg["track_buffer"] == 20
    with pytest.raises(ValueError):
        tracker_config(fps=5.0, lost_track_s=4.0, person_conf=0.1, low_conf=0.35)


def test_tracker_yaml_round_trips(tmp_path: Path) -> None:
    cfg = tracker_config(fps=10.0, lost_track_s=4.0, person_conf=0.35, low_conf=0.1)
    path = write_tracker_yaml(cfg, tmp_path)
    assert path.suffix == ".yaml" and yaml.safe_load(path.read_text()) == cfg


class FakeBoxes:
    def __init__(self) -> None:
        empty = np.zeros((0, 4))
        self.xyxy, self.cls, self.conf, self.id = empty, np.zeros(0), np.zeros(0), None


class FakeYolo:
    """Stands in for ultralytics.YOLO: records the track() arguments."""

    last: "FakeYolo | None" = None

    def __init__(self, path: str, task: str) -> None:
        self.names = NAMES
        self.calls: list[dict[str, Any]] = []
        FakeYolo.last = self

    def track(self, image: Any, **kwargs: Any) -> list[Any]:
        self.calls.append(kwargs)
        result = type("R", (), {"orig_shape": (480, 640), "boxes": FakeBoxes()})()
        return [result]


def test_detector_feeds_low_scores_to_a_generated_bytetrack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A stand-in module: importing the real ultralytics takes seconds.
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=FakeYolo))
    detector = yolo.YoloDetector("m", classes=["person", "cup"], fps=5.0, lost_track_s=4.0)
    detector.detect(np.zeros((480, 640, 3), np.uint8), ts=0.0)
    assert FakeYolo.last is not None
    [kwargs] = FakeYolo.last.calls
    assert kwargs["conf"] == yolo.TRACK_LOW_CONF
    cfg = yaml.safe_load(Path(kwargs["tracker"]).read_text())
    assert cfg["track_buffer"] == 20 and cfg["track_high_thresh"] == yolo.PERSON_CONF


MODEL = Path(__file__).parents[4] / "models" / "yolo11n_openvino_model"


@pytest.mark.integration
@pytest.mark.skipif(not MODEL.exists(), reason="run tools/download_models.py first")
def test_real_detector_runs_on_blank_image() -> None:
    from aivee_edge.adapters.yolo import YoloDetector

    detector = YoloDetector(MODEL)
    frame = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8), ts=0.0)
    assert frame.tracks == ()
