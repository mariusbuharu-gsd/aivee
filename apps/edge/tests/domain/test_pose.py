from typing import Any

import pytest
from aivee_edge.domain.pose import Keypoint, RaisedHandFilter, is_raised_hand

HIDDEN: Keypoint = (0.0, 0.0, 0.0)
NOSE, LEFT_EYE, RIGHT_EYE, LEFT_EAR, RIGHT_EAR = 0, 1, 2, 3, 4


def _person(
    *,
    nose: Keypoint = (0.50, 0.30, 0.9),
    eyes: tuple[Keypoint, Keypoint] = (HIDDEN, HIDDEN),
    ears: tuple[Keypoint, Keypoint] = (HIDDEN, HIDDEN),
    left_shoulder: Keypoint = (0.45, 0.40, 0.9),
    right_shoulder: Keypoint = (0.55, 0.40, 0.9),
    left_wrist: Keypoint = (0.44, 0.60, 0.9),
    right_wrist: Keypoint = (0.56, 0.60, 0.9),
) -> list[Keypoint]:
    """A COCO-17 skeleton of a seated guest facing the camera; arms down unless overridden."""
    kps = [HIDDEN] * 17
    kps[NOSE] = nose
    kps[LEFT_EYE], kps[RIGHT_EYE] = eyes
    kps[LEFT_EAR], kps[RIGHT_EAR] = ears
    kps[5], kps[6] = left_shoulder, right_shoulder
    kps[9], kps[10] = left_wrist, right_wrist
    return kps


def _from_behind(**overrides: Any) -> list[Keypoint]:
    """Seen from behind: no face, ears faint or hidden, both shoulders visible."""
    return _person(nose=HIDDEN, **overrides)


# -- one frame -------------------------------------------------------------------------


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


def test_the_highest_head_point_sets_the_line() -> None:
    # Eyes above the nose: a wrist just above the nose but at eye level is not raised.
    eyes = ((0.48, 0.27, 0.9), (0.52, 0.27, 0.9))
    assert is_raised_hand(_person(eyes=eyes, right_wrist=(0.56, 0.26, 0.9))) is False
    assert is_raised_hand(_person(eyes=eyes, right_wrist=(0.56, 0.20, 0.9))) is True


def test_low_confidence_wrist_is_ignored() -> None:
    assert is_raised_hand(_person(right_wrist=(0.58, 0.15, 0.2))) is False


def test_one_shoulder_is_enough_when_the_head_is_visible() -> None:
    # Seen from the side: the far shoulder is hidden behind the body.
    kps = _person(right_wrist=(0.58, 0.15, 0.9), right_shoulder=HIDDEN)
    assert is_raised_hand(kps) is True


def test_no_shoulder_means_not_raised() -> None:
    kps = _person(right_wrist=(0.58, 0.15, 0.9), left_shoulder=HIDDEN, right_shoulder=HIDDEN)
    assert is_raised_hand(kps) is False


def test_seen_from_behind_the_ears_replace_the_nose() -> None:
    ears = ((0.46, 0.31, 0.6), (0.54, 0.31, 0.6))
    assert is_raised_hand(_from_behind(ears=ears, right_wrist=(0.58, 0.15, 0.9))) is True
    assert is_raised_hand(_from_behind(ears=ears, right_wrist=(0.56, 0.33, 0.9))) is False


def test_seen_from_the_side_one_ear_and_one_shoulder_are_enough() -> None:
    kps = _person(
        nose=HIDDEN,
        ears=((0.50, 0.30, 0.8), HIDDEN),
        right_shoulder=HIDDEN,
        left_wrist=(0.47, 0.18, 0.8),
    )
    assert is_raised_hand(kps) is True


def test_no_head_point_needs_the_wrist_well_above_the_shoulders() -> None:
    # Shoulders 0.10 apart: the wrist must clear the shoulder line by 0.75 widths (0.075).
    assert is_raised_hand(_from_behind(right_wrist=(0.58, 0.30, 0.9))) is True
    assert is_raised_hand(_from_behind(right_wrist=(0.58, 0.35, 0.9))) is False  # hand on hair


def test_no_head_point_measures_the_shoulders_in_pixels() -> None:
    # On 16:9 the same 0.10 normalised shoulder width is 0.178 frame heights: 0.30 is too low.
    assert is_raised_hand(_from_behind(right_wrist=(0.58, 0.30, 0.9)), aspect=16 / 9) is False
    assert is_raised_hand(_from_behind(right_wrist=(0.58, 0.25, 0.9)), aspect=16 / 9) is True


def test_no_head_point_and_one_shoulder_means_not_raised() -> None:
    kps = _from_behind(right_shoulder=HIDDEN, right_wrist=(0.58, 0.10, 0.9))
    assert is_raised_hand(kps) is False


def test_too_few_keypoints_means_not_raised() -> None:
    assert is_raised_hand([]) is False
    assert is_raised_hand(_person()[:9]) is False


# -- over time -------------------------------------------------------------------------


def _feed(f: RaisedHandFilter, samples: list[tuple[float, bool]], track: int = 1) -> list[bool]:
    return [f.update(track, raised, ts) for ts, raised in samples]


def test_a_hand_counts_only_after_it_stayed_up_for_hold_s() -> None:
    f = RaisedHandFilter(hold_s=1.0, drop_s=0.5)
    out = _feed(f, [(t / 10, True) for t in range(12)])
    assert out == [False] * 10 + [True, True]  # 1.0 s after the first raised frame


def test_a_short_wave_never_counts() -> None:
    f = RaisedHandFilter(hold_s=1.0, drop_s=0.5)
    samples = [(t / 10, t < 5) for t in range(30)]  # up 0.5 s, then down
    assert not any(_feed(f, samples))


def test_short_drops_do_not_reset_the_hold() -> None:
    f = RaisedHandFilter(hold_s=1.0, drop_s=0.5)
    # Up 0.0-0.4, keypoints lost 0.5-0.7, up again 0.8-1.2.
    samples = [(t / 10, not 5 <= t <= 7) for t in range(13)]
    out = _feed(f, samples)
    assert out[:10] == [False] * 10 and out[10:] == [True, True, True]


def test_a_long_drop_resets_the_hold() -> None:
    f = RaisedHandFilter(hold_s=1.0, drop_s=0.5)
    samples = [(t / 10, not 5 <= t <= 11) for t in range(25)]  # 0.7 s gap
    out = _feed(f, samples)
    assert not any(out[:22]) and out[22:] == [True, True, True]  # 1.0 s after 1.2


def test_a_counted_hand_survives_short_drops_and_ends_after_a_long_one() -> None:
    f = RaisedHandFilter(hold_s=1.0, drop_s=0.5)
    _feed(f, [(t / 10, True) for t in range(11)])
    assert f.update(1, False, 1.3) is True  # 0.3 s down: still calling
    assert f.update(1, False, 1.5) is True
    assert f.update(1, False, 1.6) is False  # 0.6 s down: over
    assert f.update(1, True, 1.7) is False  # a new hold starts


def test_tracks_are_independent_and_can_be_forgotten() -> None:
    f = RaisedHandFilter(hold_s=1.0, drop_s=0.5)
    _feed(f, [(t / 10, True) for t in range(11)], track=1)
    assert f.update(2, True, 1.0) is False
    assert f.update(1, True, 1.1) is True
    f.forget(1)
    assert f.update(1, True, 1.2) is False


def test_zero_hold_counts_at_once() -> None:
    f = RaisedHandFilter(hold_s=0.0, drop_s=0.5)
    assert f.update(1, True, 0.0) is True


def test_negative_durations_are_rejected() -> None:
    with pytest.raises(ValueError):
        RaisedHandFilter(hold_s=-1.0)
    with pytest.raises(ValueError):
        RaisedHandFilter(drop_s=-0.1)
