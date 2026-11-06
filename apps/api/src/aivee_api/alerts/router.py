from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from aivee_api.alerts.audit import AuditWriter, get_audit_writer
from aivee_api.alerts.auth import AckAccess, ViewAccess
from aivee_api.alerts.schemas import AlertView, ServiceMetrics
from aivee_api.alerts.service import acknowledge, list_alerts, service_metrics
from aivee_api.deps import SessionDep

router = APIRouter(tags=["alerts"])

AuditDep = Annotated[AuditWriter, Depends(get_audit_writer)]
StateFilter = Literal["opened", "acknowledged", "arrived", "closed", "open"]


@router.post("/api/alerts/{event_id}/ack")
async def ack_alert(
    event_id: str,
    s: SessionDep,
    access: AckAccess,
    audit: AuditDep,
    location_id: str | None = None,
) -> AlertView:
    return await acknowledge(s, access, event_id, audit, location_id)


@router.get("/api/alerts")
async def get_alerts(
    s: SessionDep,
    access: ViewAccess,
    location_id: str | None = None,
    state: Annotated[
        StateFilter | None, Query(description="Current state; `open` = not closed yet")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[AlertView]:
    return await list_alerts(s, access, location_id, state, limit)


@router.get("/api/metrics/service", response_model_by_alias=True)
async def get_service_metrics(
    s: SessionDep,
    access: ViewAccess,
    location_id: str | None = None,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
) -> ServiceMetrics:
    return await service_metrics(s, access, location_id, start, end)
