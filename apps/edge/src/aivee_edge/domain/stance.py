"""Is a person standing? Per-frame stance from pose keypoints, with a box-shape fallback.

Staff stand and walk; guests sit. Pose first: the knee angle (hip-knee-ankle) of the
straightest visible leg. A straight leg (>= 150°) means standing, also mid-stride where
the other leg is bent; a clearly bent knee (<= 120°) on every visible leg means seated.
When no leg is fully visible (table in the way) or the angle is in between, the box
shape decides: a tall box (height / width >= 2.2 in pixels) is standing, a squat one
(<= 1.6) is seated. Anything else is unknown (None) and is left out of the ratio.

Keypoints are COCO-17 (x, y, confidence) in normalised coordinates; `aspect` is the
frame's width / height, needed to measure angles and box shapes in pixels.
"""

import math
from collections.abc import Sequence

from aivee_edge.domain.observation import BBox
from aivee_edge.domain.pose import MIN_CONFIDENCE, Keypoint

LEFT_HIP, RIGHT_HIP = 11, 12
LEFT_KNEE, RIGHT_KNEE = 13, 14
LEFT_ANKLE, RIGHT_ANKLE = 15, 16
LEGS = ((LEFT_HIP, LEFT_KNEE, LEFT_ANKLE), (RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE))

STANDING_KNEE_DEG = 150.0
"""Straightest visible knee at or above this → standing."""
SEATED_KNEE_DEG = 120.0
"""Straightest visible knee at or below this → seated."""
STANDING_BOX_RATIO = 2.2
"""Pixel height / width at or above this → standing (an upright adult is ~2.5-3.5)."""
SEATED_BOX_RATIO = 1.6
"""Pixel height / width at or below this → seated (upper body over a table is ~1.2-1.6)."""


def knee_angle(
    hip: Keypoint, knee: Keypoint, ankle: Keypoint, *, aspect: float = 1.0
) -> float | None:
    """Angle at the knee in degrees (180 = straight leg), measured in pixel space."""
    ux, uy = (hip[0] - knee[0]) * aspect, hip[1] - knee[1]
    vx, vy = (ankle[0] - knee[0]) * aspect, ankle[1] - knee[1]
    nu, nv = math.hypot(ux, uy), math.hypot(vx, vy)
    if nu == 0 or nv == 0:
        return None
    cos = max(-1.0, min(1.0, (ux * vx + uy * vy) / (nu * nv)))
    return math.degrees(math.acos(cos))


def pose_standing(
    keypoints: Sequence[Keypoint],
    *,
    aspect: float = 1.0,
    min_confidence: float = MIN_CONFIDENCE,
) -> bool | None:
    """Stance from the straightest fully visible leg; None if no leg decides it."""
    if len(keypoints) <= RIGHT_ANKLE:
        return None
    angles = []
    for hip_i, knee_i, ankle_i in LEGS:
        hip, knee, ankle = keypoints[hip_i], keypoints[knee_i], keypoints[ankle_i]
        if min(hip[2], knee[2], ankle[2]) < min_confidence:
            continue
        angle = knee_angle(hip, knee, ankle, aspect=aspect)
        if angle is not None:
            angles.append(angle)
    if not angles:
        return None
    straightest = max(angles)
    if straightest >= STANDING_KNEE_DEG:
        return True
    if straightest <= SEATED_KNEE_DEG:
        return False
    return None


def bbox_standing(bbox: BBox, aspect: float | None) -> bool | None:
    """Stance from the box's pixel height / width; None when unknown or ambiguous."""
    if aspect is None:
        return None
    x1, y1, x2, y2 = bbox
    width, height = (x2 - x1) * aspect, y2 - y1
    if width <= 0 or height <= 0:
        return None
    ratio = height / width
    if ratio >= STANDING_BOX_RATIO:
        return True
    if ratio <= SEATED_BOX_RATIO:
        return False
    return None


def is_standing(
    keypoints: Sequence[Keypoint] | None, bbox: BBox, aspect: float | None
) -> bool | None:
    """Pose when it decides, else the box shape, else None (unknown)."""
    if keypoints is not None:
        from_pose = pose_standing(keypoints, aspect=aspect or 1.0)
        if from_pose is not None:
            return from_pose
    return bbox_standing(bbox, aspect)
