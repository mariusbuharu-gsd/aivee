import math

import pytest
from aivee_edge.domain.behaviour import TrajectoryBuffer
from aivee_edge.domain.observation import BBox, Frame, TrackObs
from aivee_edge.domain.pose import Keypoint
from aivee_edge.domain.stance import (
    LEFT_ANKLE,
    LEFT_HIP,
    LEFT_KNEE,
    RIGHT_ANKLE,
    RIGHT_HIP,
    RIGHT_KNEE,
    bbox_standing,
    is_standing,
    knee_angle,
    pose_standing,
)

Leg = tuple[Keypoint, Keypoint, Keypoint]

HIDDEN: Keypoint = (0.0, 0.0, 0.0)
TALL: BBox = (0.45, 0.2, 0.55, 0.8)  # 0.1 x 0.6 → ratio 6 on a square frame
WIDE: BBox = (0.4, 0.4, 0.6, 0.6)  # ratio 1

STRAIGHT: Leg = ((0.5, 0.5, 0.9), (0.5, 0.65, 0.9), (0.5, 0.8, 0.9))
BENT: Leg = ((0.5, 0.5, 0.9), (0.6, 0.5, 0.9), (0.6, 0.6, 0.9))  # thigh forward, shin down: 90°


def _legs(left: Leg | None, right: Leg | None = None) -> list[Keypoint]:
    kps = [HIDDEN] * 17
    sides = (
        (left, (LEFT_HIP, LEFT_KNEE, LEFT_ANKLE)),
        (right, (RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE)),
    )
    for leg, (h, k, a) in sides:
        if leg is not None:
            kps[h], kps[k], kps[a] = leg
    return kps


def test_knee_angle_of_straight_and_bent_legs() -> None:
    assert knee_angle(*STRAIGHT) == pytest.approx(180.0)
    assert knee_angle(*BENT) == pytest.approx(90.0)
    assert knee_angle((0.5, 0.5, 1), (0.5, 0.5, 1), (0.5, 0.8, 1)) is None  # degenerate


def test_knee_angle_uses_pixel_space() -> None:
    hip, knee, ankle = (0.5, 0.5, 1.0), (0.5, 0.6, 1.0), (0.6, 0.7, 1.0)
    assert knee_angle(hip, knee, ankle) == pytest.approx(135.0)
    # On a 16:9 frame the same normalised offsets are wider in pixels: a more open knee.
    expected = 90 + math.degrees(math.atan2(0.1, 0.1 * 16 / 9))
    assert knee_angle(hip, knee, ankle, aspect=16 / 9) == pytest.approx(expected)


def test_pose_standing_from_the_straightest_visible_leg() -> None:
    assert pose_standing(_legs(STRAIGHT)) is True
    assert pose_standing(_legs(BENT, BENT)) is False
    # Mid-stride: one straight leg carries the weight.
    assert pose_standing(_legs(BENT, STRAIGHT)) is True


def test_pose_standing_unknown_without_visible_legs_or_with_an_ambiguous_knee() -> None:
    assert pose_standing([HIDDEN] * 17) is None
    assert pose_standing([]) is None
    faint: Leg = ((0.5, 0.5, 0.1), (0.5, 0.65, 0.1), (0.5, 0.8, 0.1))
    assert pose_standing(_legs(faint)) is None
    half_bent: Leg = ((0.5, 0.5, 0.9), (0.5, 0.6, 0.9), (0.6, 0.7, 0.9))  # 135°
    assert pose_standing(_legs(half_bent)) is None


def test_bbox_fallback_uses_pixel_height_over_width() -> None:
    assert bbox_standing(TALL, 1.0) is True
    assert bbox_standing(WIDE, 1.0) is False
    # 0.1 x 0.4 normalised on 16:9 → (0.4 · 9) / (0.1 · 16) = 2.25 in pixels.
    assert bbox_standing((0.4, 0.2, 0.5, 0.6), 16 / 9) is True
    assert bbox_standing((0.4, 0.2, 0.5, 0.6), 2.0) is None  # ratio 2.0: ambiguous band
    assert bbox_standing(TALL, None) is None  # frame size unknown
    assert bbox_standing((0.4, 0.4, 0.4, 0.6), 1.0) is None  # degenerate box


def test_is_standing_prefers_pose_and_falls_back_to_the_box() -> None:
    assert is_standing(_legs(BENT, BENT), TALL, 1.0) is False
    assert is_standing(_legs(STRAIGHT), WIDE, 1.0) is True
    assert is_standing(None, TALL, 1.0) is True
    assert is_standing([HIDDEN] * 17, WIDE, 1.0) is False
    assert is_standing(None, TALL, None) is None


def _observe(buf: TrajectoryBuffer, ts: float, standing: bool | None) -> None:
    track = TrackObs(track_id=1, bbox=TALL, standing=standing)
    buf.observe(Frame(ts=ts, tracks=(track,)))


def test_standing_ratio_over_a_short_window() -> None:
    buf = TrajectoryBuffer()
    for i in range(31):  # 0 .. 3 s at 10 fps, seated
        _observe(buf, i / 10, False)
    assert buf.features(1, {}).standing_ratio == 0.0
    for i in range(31, 41):  # stands up for 1 s: 10 of the 31 samples in the window
        _observe(buf, i / 10, True)
    assert buf.features(1, {}).standing_ratio == pytest.approx(10 / 31)
    for i in range(41, 81):  # keeps standing: the seated samples age out of the 3 s window
        _observe(buf, i / 10, True)
    assert buf.features(1, {}).standing_ratio == pytest.approx(1.0)


def test_standing_ratio_needs_some_history_and_ignores_unknown_frames() -> None:
    buf = TrajectoryBuffer()
    assert buf.features(1, {}).standing_ratio is None
    _observe(buf, 0.0, None)
    assert buf.features(1, {}).standing_ratio is None
    _observe(buf, 0.1, True)
    _observe(buf, 0.6, True)
    assert buf.features(1, {}).standing_ratio == pytest.approx(0.25)  # 0.5 s of the 2 s needed
    for i in range(7, 31):
        _observe(buf, i / 10, None if i % 2 else True)
    assert buf.features(1, {}).standing_ratio == pytest.approx(1.0)


def test_forget_drops_stance_history() -> None:
    buf = TrajectoryBuffer()
    _observe(buf, 0.0, True)
    buf.forget(1)
    assert buf.features(1, {}).standing_ratio is None
