"""Raised-hand detection from COCO-17 pose keypoints.

Keypoints are (x, y, confidence) in normalised image coordinates, y growing downward,
so "above" means a smaller y.
"""

from collections.abc import Sequence

Keypoint = tuple[float, float, float]

NOSE = 0
LEFT_SHOULDER, RIGHT_SHOULDER = 5, 6
LEFT_WRIST, RIGHT_WRIST = 9, 10

MIN_CONFIDENCE = 0.3
NOSE_MARGIN = 0.03
"""How far (normalised units) a wrist must be above the nose; ignores hands at the face."""


def _visible(kp: Keypoint, min_confidence: float) -> bool:
    return kp[2] >= min_confidence


def is_raised_hand(
    keypoints: Sequence[Keypoint],
    *,
    min_confidence: float = MIN_CONFIDENCE,
    nose_margin: float = NOSE_MARGIN,
) -> bool:
    """True if either wrist is above its shoulder and above the nose by `nose_margin`.

    Any needed point that is missing or below `min_confidence` counts as "not raised".
    """
    if len(keypoints) <= RIGHT_WRIST:
        return False
    nose = keypoints[NOSE]
    if not _visible(nose, min_confidence):
        return False
    for shoulder_i, wrist_i in ((LEFT_SHOULDER, LEFT_WRIST), (RIGHT_SHOULDER, RIGHT_WRIST)):
        shoulder, wrist = keypoints[shoulder_i], keypoints[wrist_i]
        if not (_visible(shoulder, min_confidence) and _visible(wrist, min_confidence)):
            continue
        if wrist[1] < shoulder[1] and wrist[1] < nose[1] - nose_margin:
            return True
    return False
