from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AlertEvent(BaseModel):
    """Published by the edge when a rule's situation starts or stops holding."""

    event_id: str = Field(description="UUID; idempotency key for ingest")
    rule_id: str
    camera_id: str
    zone_id: str
    state: Literal["opened", "closed"]
    at: datetime
    summary_ro: str
    snapshot: bool = False


class DeviceStatus(BaseModel):
    """Retained on `status`; the broker publishes `offline` as the device's last will."""

    device: str
    state: Literal["online", "offline"]
    version: str = "0.1.0"
    cameras: list[str] = Field(default_factory=list)


class Metrics(BaseModel):
    device: str
    fps: float
    verified_ratio: float = Field(description="Share of frames sent to the heavy model")
    cpu_percent: float


class StaffSuggestion(BaseModel):
    """The edge thinks a tracked person is staff and asks the owner to confirm."""

    suggestion_id: str
    camera_id: str
    track_id: int
    staff_score: float = Field(ge=0, le=1)
    reason_ro: str
    snapshot: bool = Field(
        default=False,
        description="A face-blurred person crop was sent on `snapshots/{suggestion_id}`",
    )


class StaffProfile(BaseModel):
    """Appearance centroid of a staff role, retained on `profiles`."""

    id: str
    name: str
    description_ro: str = ""
    centroid: list[float] = Field(description="L2-normalised image embedding")


class StaffProfiles(BaseModel):
    device: str
    profiles: list[StaffProfile]
