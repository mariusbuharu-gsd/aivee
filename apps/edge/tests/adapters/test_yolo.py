from pathlib import Path

import numpy as np
import pytest
from aivee_edge.adapters.yolo import DEFAULT_CLASSES, class_ids_for, map_results
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


def test_class_ids_for_excludes_dining_table_and_rejects_unknown() -> None:
    assert "dining table" not in DEFAULT_CLASSES
    assert class_ids_for(NAMES, ["person", "cup"]) == [0, 41]
    with pytest.raises(ValueError):
        class_ids_for(NAMES, ["unicorn"])


MODEL = Path(__file__).parents[4] / "models" / "yolo11n_openvino_model"


@pytest.mark.integration
@pytest.mark.skipif(not MODEL.exists(), reason="run tools/download_models.py first")
def test_real_detector_runs_on_blank_image() -> None:
    from aivee_edge.adapters.yolo import YoloDetector

    detector = YoloDetector(MODEL)
    frame = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8), ts=0.0)
    assert frame.tracks == ()
