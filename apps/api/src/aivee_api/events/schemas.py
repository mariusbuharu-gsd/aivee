from typing import Literal

from aivee_contracts.events import AlertEvent, StaffSuggestion
from pydantic import BaseModel

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
