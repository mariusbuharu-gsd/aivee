from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from aivee_api.alerts.domain import AlertState
from aivee_api.alerts.schemas import AlertView
from aivee_api.db.models import VideoUploadRow

VideoStatus = Literal["queued", "running", "done", "failed"]


class CreatedBy(BaseModel):
    id: str
    name: str


class VideoOut(BaseModel):
    """An uploaded clip and how far its analysis got."""

    id: str
    location_id: str
    camera_id: str = Field(description="The virtual camera `video-<id>` its alerts belong to")
    source_camera_id: str | None = Field(description="The camera whose zones and rules it uses")
    filename: str
    size_bytes: int
    rotate: int
    status: VideoStatus
    progress: float = Field(ge=0, le=1)
    duration_s: float | None
    events: int = Field(description="Alerts found so far")
    error_ro: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    created_by: CreatedBy | None

    @classmethod
    def of(cls, row: VideoUploadRow, events: int) -> "VideoOut":
        by = (
            CreatedBy(id=row.created_by_id, name=row.created_by_name or "")
            if row.created_by_id
            else None
        )
        return cls(
            id=row.id,
            location_id=row.location_id,
            camera_id=row.camera_id,
            source_camera_id=row.source_camera_id,
            filename=row.filename,
            size_bytes=row.size_bytes,
            rotate=row.rotate,
            status=row.status,  # type: ignore[arg-type]  # CHECK constraint keeps it valid
            progress=min(1.0, max(0.0, row.progress)),
            duration_s=row.duration_s,
            events=events,
            error_ro=row.error_ro,
            created_at=row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
            created_by=by,
        )


def _offset(at: datetime | None, epoch: datetime) -> float | None:
    return None if at is None else round(max(0.0, (at - epoch).total_seconds()), 1)


class VideoAlert(BaseModel):
    """One alert found in a clip; times are positions in the clip, in seconds."""

    event_id: str
    zone_id: str
    zone_name: str
    summary_ro: str
    state: AlertState
    at_s: float = Field(description="Opened, as a position in the clip")
    arrived_at_s: float | None
    closed_at_s: float | None
    wait_s: float | None
    closed_reason: str | None
    snapshot_url: str | None

    @classmethod
    def of(cls, view: AlertView, epoch: datetime) -> "VideoAlert":
        return cls(
            event_id=view.event_id,
            zone_id=view.zone_id,
            zone_name=view.zone_name,
            summary_ro=view.summary_ro,
            state=view.state,
            at_s=_offset(view.opened_at, epoch) or 0.0,
            arrived_at_s=_offset(view.arrived_at, epoch),
            closed_at_s=_offset(view.closed_at, epoch),
            wait_s=view.wait_s,
            closed_reason=view.closed_reason,
            snapshot_url=view.snapshot_url,
        )
