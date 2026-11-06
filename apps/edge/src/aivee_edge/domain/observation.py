"""What the edge sees in one frame, in pure domain terms (no cv2/numpy/torch).

Adapters (YOLO, tracker, pose, role scoring) produce `Frame`s; the situation
engine consumes them. Boxes are normalised (x1, y1, x2, y2) in [0, 1].
"""

from dataclasses import dataclass, field
from typing import Literal

BBox = tuple[float, float, float, float]
PersonRole = Literal["guest", "staff"]


@dataclass(frozen=True)
class TrackObs:
    """A tracked person in this frame."""

    track_id: int
    bbox: BBox
    confidence: float = 1.0
    role: PersonRole = "guest"
    staff_score: float = 0.0
    raised_hand: bool = False


@dataclass(frozen=True)
class ObjectObs:
    """A non-person object (COCO class name), e.g. "cup", "bottle", "bowl"."""

    label: str
    bbox: BBox
    confidence: float = 1.0


@dataclass(frozen=True)
class Frame:
    ts: float  # seconds, monotonic
    tracks: tuple[TrackObs, ...] = ()
    objects: tuple[ObjectObs, ...] = field(default_factory=tuple)
