import statistics
from datetime import UTC, datetime
from typing import Annotated

from aivee_contracts.events import Metrics
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from aivee_api.auth.deps import Access, require
from aivee_api.auth.permissions import ALERTS_VIEW
from aivee_api.auth.scope import events_at
from aivee_api.db.models import EventRow
from aivee_api.db.repositories import DeviceRepository
from aivee_api.deps import ServicesDep, SessionDep

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


class DashboardMetrics(BaseModel):
    devices: list[Metrics]
    devices_online: int
    devices_total: int
    events_today: int
    alert_latency_ms: float | None = None
    """Median delay between the edge raising an event and the server storing it (today)."""


@router.get("")
async def get_metrics(
    s: SessionDep, svc: ServicesDep, access: Annotated[Access, Depends(require(ALERTS_VIEW))]
) -> DashboardMetrics:
    loc = access.location_id
    devices = [d for d in await DeviceRepository(s).list_all() if d.site_id == loc]
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    today = (await s.scalars(events_at(loc).where(EventRow.at >= midnight))).all()
    delays = [
        (e.received_at - e.at).total_seconds() * 1000
        for e in today
        if e.state == "opened" and e.received_at >= e.at
    ]
    return DashboardMetrics(
        devices=[sample.metrics for sample in svc.metrics.latest() if sample.site == loc],
        devices_online=sum(d.state == "online" for d in devices),
        devices_total=len(devices),
        events_today=sum(e.state == "opened" for e in today),
        alert_latency_ms=round(statistics.median(delays), 1) if delays else None,
    )
