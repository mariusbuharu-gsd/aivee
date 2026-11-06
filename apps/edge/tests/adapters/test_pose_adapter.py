import pytest
from aivee_edge.adapters.pose import iou, match_by_iou, normalise_keypoints


def test_iou_identical_disjoint_and_half() -> None:
    assert iou((0, 0, 1, 1), (0, 0, 1, 1)) == 1.0
    assert iou((0, 0, 0.2, 0.2), (0.5, 0.5, 1, 1)) == 0.0
    assert iou((0, 0, 0.5, 1), (0, 0, 1, 1)) == pytest.approx(0.5)


def test_match_by_iou_assigns_best_one_to_one() -> None:
    tracks = {1: (0.0, 0.0, 0.4, 1.0), 2: (0.5, 0.0, 0.9, 1.0)}
    detections = [(0.52, 0.0, 0.92, 1.0), (0.02, 0.0, 0.42, 1.0)]
    assert match_by_iou(tracks, detections) == {1: 1, 2: 0}


def test_match_by_iou_drops_low_overlap_and_duplicates() -> None:
    tracks = {1: (0.0, 0.0, 0.4, 1.0), 2: (0.01, 0.0, 0.41, 1.0), 3: (0.8, 0.8, 0.9, 0.9)}
    detections = [(0.0, 0.0, 0.4, 1.0)]
    assert match_by_iou(tracks, detections) == {1: 0}


def test_match_by_iou_empty() -> None:
    assert match_by_iou({}, [(0, 0, 1, 1)]) == {}
    assert match_by_iou({1: (0, 0, 1, 1)}, []) == {}


def test_normalise_keypoints() -> None:
    kps = normalise_keypoints([[320, 240], [0, 480]], [0.9, 0.1], 640, 480)
    assert kps == ((0.5, 0.5, 0.9), (0.0, 1.0, 0.1))
    assert normalise_keypoints([[64, 48]], None, 640, 480) == ((0.1, 0.1, 1.0),)
