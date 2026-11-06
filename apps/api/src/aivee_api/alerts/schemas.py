from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from aivee_api.alerts.domain import AlertState, ClosedBy, CloseReason, Measure, ServiceStats


class AlertView(BaseModel):
    """One alert, folded from its events and the acknowledgement (spec: Alert lifecycle).

    `state`, `at`, `snapshot`, `snapshot_url` and `device_id` keep the shape of the raw
    event messages, so a dashboard that still folds raw events can read (and, by
    `event_id`, de-duplicate) these too.
    """

    event_id: str = Field(description="The opened event's id: the alert's id")
    rule_id: str
    location_id: str | None
    camera_id: str
    zone_id: str
    zone_name: str
    summary_ro: str
    opened_at: datetime
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = Field(
        None, description='Who pressed "Merg eu": their name at that moment (a snapshot)'
    )
    acknowledged_by_id: str | None = None
    realerted_at: datetime | None = Field(
        None,
        description="When the whole shift was told again that nobody arrived after the ack "
        "(REALERT_AFTER_S, once per alert)",
    )
    arrived_at: datetime | None = None
    closed_at: datetime | None = None
    closed_by: ClosedBy | None = Field(
        None, description='"edge" (the situation ended) or "system" (see closed_reason)'
    )
    closed_reason: CloseReason | None = Field(
        None,
        description="Why the system closed it: device_offline | device_restarted | camera_deleted",
    )
    wait_s: float | None = Field(None, description="arrived (or closed) - opened")
    reaction_s: float | None = Field(None, description="acknowledged - opened")
    travel_s: float | None = Field(None, description="arrived - acknowledged")
    unacknowledged_arrival: bool = Field(False, description='"fără preluare"')
    state: AlertState
    at: datetime = Field(description="Time of the latest change")
    device_id: str = ""
    snapshot: bool = False
    snapshot_url: str | None = None


class AlertViewMessage(BaseModel):
    """Pushed on /ws/events whenever an alert changes (opened, ack, re-alert, arrived,
    closed)."""

    type: Literal["alert"] = "alert"
    data: AlertView


class MeasureOut(BaseModel):
    count: int
    median_s: float | None
    p90_s: float | None

    @classmethod
    def of(cls, m: Measure) -> "MeasureOut":
        return cls(count=m.count, median_s=m.median_s, p90_s=m.p90_s)


class ServiceMetrics(BaseModel):
    location_id: str | None
    from_: datetime = Field(serialization_alias="from")
    to: datetime
    alerts: int
    unacknowledged_arrivals: int
    wait: MeasureOut
    reaction: MeasureOut
    travel: MeasureOut

    @classmethod
    def of(
        cls, stats: ServiceStats, location_id: str | None, start: datetime, end: datetime
    ) -> "ServiceMetrics":
        return cls(
            location_id=location_id,
            from_=start,
            to=end,
            alerts=stats.alerts,
            unacknowledged_arrivals=stats.unacknowledged_arrivals,
            wait=MeasureOut.of(stats.wait),
            reaction=MeasureOut.of(stats.reaction),
            travel=MeasureOut.of(stats.travel),
        )
