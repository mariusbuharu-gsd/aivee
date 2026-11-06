from typing import Literal

from aivee_contracts.detections import Detections
from aivee_contracts.events import AlertEvent, StaffSuggestion
from pydantic import BaseModel, Field

from aivee_api.db.models import EventRow, SuggestionRow


class EventOut(AlertEvent):
    device_id: str = ""
    snapshot_url: str | None = None


class SuggestionOut(StaffSuggestion):
    device_id: str = ""
    status: str = "pending"


def event_out(row: EventRow) -> EventOut:
    return EventOut(
        event_id=row.event_id,
        rule_id=row.rule_id,
        camera_id=row.camera_id,
        zone_id=row.zone_id,
        state=row.state,  # type: ignore[arg-type]  # CHECK constraint keeps it valid
        at=row.at,
        summary_ro=row.summary_ro,
        snapshot=row.snapshot_path is not None,
        device_id=row.device_id,
        snapshot_url=f"/api/snapshots/{row.event_id}" if row.snapshot_path else None,
    )


def suggestion_out(row: SuggestionRow) -> SuggestionOut:
    return SuggestionOut(
        suggestion_id=row.suggestion_id,
        camera_id=row.camera_id,
        track_id=row.track_id,
        staff_score=row.staff_score,
        reason_ro=row.reason_ro,
        device_id=row.device_id,
        status=row.status,
    )


class AlertMessage(BaseModel):
    type: Literal["alert"] = "alert"
    data: EventOut


class SuggestionMessage(BaseModel):
    type: Literal["suggestion"] = "suggestion"
    data: SuggestionOut


class LiveDetection(BaseModel):
    """One person as the dashboard draws it (apps/dashboard/src/api/client.ts `Detection`)."""

    track_id: int
    role: Literal["guest", "staff"]
    box: tuple[float, float, float, float] = Field(description="Normalised [x, y, width, height]")
    staff_score: float
    raised_hand: bool


class DetectionsMessage(BaseModel):
    type: Literal["detections"] = "detections"
    camera_id: str
    data: list[LiveDetection]

    @classmethod
    def from_detections(cls, d: Detections) -> "DetectionsMessage":
        return cls(
            camera_id=d.camera_id,
            data=[
                LiveDetection(
                    track_id=t.track_id,
                    role=t.role,
                    box=(t.bbox[0], t.bbox[1], t.bbox[2] - t.bbox[0], t.bbox[3] - t.bbox[1]),
                    staff_score=t.staff_score,
                    raised_hand=t.raised_hand,
                )
                for t in d.tracks
            ],
        )
