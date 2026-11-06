from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

Unit = Annotated[float, Field(ge=0, le=1)]
NormBox = tuple[Unit, Unit, Unit, Unit]
"""Normalised (x1, y1, x2, y2) in [0, 1]."""


class DetectedTrack(BaseModel):
    track_id: int
    bbox: NormBox
    role: Literal["guest", "staff"]
    staff_score: float = Field(ge=0, le=1)
    raised_hand: bool = False


class DetectedObject(BaseModel):
    label: str = Field(description="COCO class name")
    bbox: NormBox


class Detections(BaseModel):
    """What one camera sees right now, for the live overlay. Edge → `detections`, QoS 0,
    not retained, at most 5 per second."""

    camera_id: str
    ts: datetime
    tracks: list[DetectedTrack] = Field(default_factory=list)
    objects: list[DetectedObject] = Field(default_factory=list)
