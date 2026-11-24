"""Raised-hand detection from COCO-17 pose keypoints, per frame and over time.

Keypoints are (x, y, confidence) in normalised image coordinates, y growing downward,
so "above" means a smaller y.

Per frame (`is_raised_hand`): a visible wrist above a line that depends on what the pose
model sees of the person:
- any head point (nose, eyes, ears): `head_margin` above the highest one, so a hand at
  the face (drinking, a phone call) does not count. Ears make guests seen from behind
  or from the side count, not only those facing the camera;
- no head point but both shoulders (seen from behind, head turned away or cropped): the
  shoulder line minus `HEADLESS_SHOULDER_WIDTHS` shoulder widths, measured in pixels,
  i.e. roughly the top of the head;
- otherwise (one shoulder and no head, or no shoulder): not raised.

Over time (`RaisedHandFilter`): a hand counts only after it has been up for `hold_s`
(a wave or one bad frame is not a call), and gaps of up to `drop_s` without a raised
frame (keypoints lost, motion blur) neither reset the hold nor end a counted hand.
"""

from collections.abc import Sequence
from dataclasses import dataclass

Keypoint = tuple[float, float, float]

NOSE = 0
LEFT_EYE, RIGHT_EYE = 1, 2
LEFT_EAR, RIGHT_EAR = 3, 4
HEAD = (NOSE, LEFT_EYE, RIGHT_EYE, LEFT_EAR, RIGHT_EAR)
LEFT_SHOULDER, RIGHT_SHOULDER = 5, 6
LEFT_WRIST, RIGHT_WRIST = 9, 10

MIN_CONFIDENCE = 0.3
HEAD_MARGIN = 0.03
"""How far (normalised units) a wrist must be above the highest head point."""
HEADLESS_SHOULDER_WIDTHS = 0.75
"""Without a head point, how many shoulder widths a wrist must clear the shoulder line by
(a head is about 0.75 shoulder widths tall above it)."""

RAISED_HAND_HOLD_S = 1.0
"""A hand counts as raised only after this long up."""
RAISED_HAND_DROP_S = 0.6
"""Gaps up to this long without a raised frame neither reset the hold nor end a hand."""


def _visible(kp: Keypoint, min_confidence: float) -> bool:
    return kp[2] >= min_confidence


def raise_line(
    keypoints: Sequence[Keypoint],
    *,
    min_confidence: float = MIN_CONFIDENCE,
    head_margin: float = HEAD_MARGIN,
    aspect: float = 1.0,
) -> float | None:
    """The y a wrist must be above to count as raised; None when the pose cannot tell."""
    if len(keypoints) <= RIGHT_WRIST:
        return None
    shoulders = [
        keypoints[i]
        for i in (LEFT_SHOULDER, RIGHT_SHOULDER)
        if _visible(keypoints[i], min_confidence)
    ]
    if not shoulders:
        return None
    shoulder_y = min(s[1] for s in shoulders)
    head = [keypoints[i][1] for i in HEAD if _visible(keypoints[i], min_confidence)]
    if head:
        return min(min(head) - head_margin, shoulder_y)
    if len(shoulders) < 2:
        return None
    width = abs(shoulders[0][0] - shoulders[1][0]) * aspect  # in frame heights
    if width <= 0:
        return None
    return shoulder_y - HEADLESS_SHOULDER_WIDTHS * width


def is_raised_hand(
    keypoints: Sequence[Keypoint],
    *,
    min_confidence: float = MIN_CONFIDENCE,
    head_margin: float = HEAD_MARGIN,
    aspect: float = 1.0,
) -> bool:
    """True if a visible wrist is above `raise_line` in this frame.

    `aspect` is the frame's width / height, used to measure shoulder width in pixels.
    Any needed point that is missing or below `min_confidence` counts as "not raised".
    """
    line = raise_line(
        keypoints, min_confidence=min_confidence, head_margin=head_margin, aspect=aspect
    )
    if line is None:
        return False
    return any(
        _visible(keypoints[i], min_confidence) and keypoints[i][1] < line
        for i in (LEFT_WRIST, RIGHT_WRIST)
    )


@dataclass
class _Hold:
    since: float
    """First raised frame of this hold."""
    last_up: float
    """Latest raised frame."""


class RaisedHandFilter:
    """Per-track temporal smoothing of the per-frame raised-hand flag, with hysteresis.

    A hold starts at the first raised frame and continues across gaps of at most `drop_s`.
    The hand counts once the raised frames of one hold span `hold_s`, and keeps counting
    until no raised frame has been seen for more than `drop_s`.
    """

    def __init__(
        self, hold_s: float = RAISED_HAND_HOLD_S, drop_s: float = RAISED_HAND_DROP_S
    ) -> None:
        if hold_s < 0 or drop_s < 0:
            raise ValueError("hold_s and drop_s must not be negative")
        self._hold_s = hold_s
        self._drop_s = drop_s
        self._holds: dict[int, _Hold] = {}

    def update(self, track_id: int, raised: bool, ts: float) -> bool:
        """Feed this frame's flag for a track; True while its hand counts as raised."""
        hold = self._holds.get(track_id)
        if hold is not None and ts - hold.last_up > self._drop_s:
            del self._holds[track_id]
            hold = None
        if raised:
            if hold is None:
                hold = self._holds[track_id] = _Hold(since=ts, last_up=ts)
            else:
                hold.last_up = ts
        return hold is not None and hold.last_up - hold.since >= self._hold_s

    def forget(self, track_id: int) -> None:
        self._holds.pop(track_id, None)
