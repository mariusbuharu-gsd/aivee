from aivee_edge.domain.pose import Keypoint, is_raised_hand

HIDDEN: Keypoint = (0.0, 0.0, 0.0)


def _person(
    *,
    nose: Keypoint = (0.50, 0.30, 0.9),
    left_shoulder: Keypoint = (0.45, 0.40, 0.9),
    right_shoulder: Keypoint = (0.55, 0.40, 0.9),
    left_wrist: Keypoint = (0.44, 0.60, 0.9),
    right_wrist: Keypoint = (0.56, 0.60, 0.9),
) -> list[Keypoint]:
    """A COCO-17 skeleton of a seated guest; arms down unless overridden."""
    kps = [HIDDEN] * 17
    kps[0] = nose
    kps[5], kps[6] = left_shoulder, right_shoulder
    kps[9], kps[10] = left_wrist, right_wrist
    return kps


def test_arms_down_is_not_raised() -> None:
    assert is_raised_hand(_person()) is False


def test_right_wrist_above_head_is_raised() -> None:
    assert is_raised_hand(_person(right_wrist=(0.58, 0.15, 0.8))) is True


def test_left_wrist_above_head_is_raised() -> None:
    assert is_raised_hand(_person(left_wrist=(0.42, 0.15, 0.8))) is True


def test_wrist_above_shoulder_but_below_nose_is_not_raised() -> None:
    # Hand at chin height (e.g. drinking) is not a call for service.
    assert is_raised_hand(_person(right_wrist=(0.55, 0.33, 0.9))) is False


def test_wrist_barely_above_nose_is_within_margin() -> None:
    assert is_raised_hand(_person(right_wrist=(0.55, 0.29, 0.9))) is False


def test_low_confidence_wrist_is_ignored() -> None:
    assert is_raised_hand(_person(right_wrist=(0.58, 0.15, 0.2))) is False


def test_missing_shoulder_means_not_raised() -> None:
    assert is_raised_hand(_person(right_wrist=(0.58, 0.15, 0.9), right_shoulder=HIDDEN)) is False


def test_missing_nose_means_not_raised() -> None:
    assert is_raised_hand(_person(right_wrist=(0.58, 0.15, 0.9), nose=HIDDEN)) is False


def test_too_few_keypoints_means_not_raised() -> None:
    assert is_raised_hand([]) is False
    assert is_raised_hand(_person()[:9]) is False
