from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

BEFORE_SUFFIX = "-before"


def before_snapshot_id(event_id: str) -> str:
    """Snapshot id of the "before" image of an object change (`snapshots/<id>-before`)."""
    return f"{event_id}{BEFORE_SUFFIX}"


class ObjectChange(BaseModel):
    """What changed for an `object_gone` alert: the COCO classes that disappeared."""

    kind: Literal["gone"] = "gone"
    objects: list[str] = Field(description="COCO class names that disappeared")
    before_snapshot: bool = Field(
        default=False,
        description="The last frame with the object was sent on `snapshots/<event_id>-before`",
    )


VerificationStatus = Literal["pending", "confirmed", "rejected", "unavailable"]


class Verification(BaseModel):
    """A vision model's second opinion on an opened alert (ingest, at most one per alert).

    pending: being checked · confirmed / rejected: the model's answer · unavailable: not
    checked (feature off, no key, timeout, error, no image); the alert is a normal one.
    """

    status: VerificationStatus
    summary_ro: str = Field(default="", description='e.g. "Masa 1: a dispărut paharul de vin"')
    object_ro: str | None = Field(default=None, description="Romanian name of the object, if any")
    model: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)


class AlertEvent(BaseModel):
    """Published by the edge when a rule's situation starts or stops holding, and once in
    between (`arrived`) when a staff member has stayed in the zone for ARRIVE_S."""

    event_id: str = Field(description="UUID; idempotency key for ingest")
    rule_id: str
    camera_id: str
    zone_id: str
    state: Literal["opened", "arrived", "closed"]
    at: datetime
    summary_ro: str
    snapshot: bool = False
    object_change: ObjectChange | None = Field(
        default=None, description="Set on `opened` events of an `object_gone` rule"
    )


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
