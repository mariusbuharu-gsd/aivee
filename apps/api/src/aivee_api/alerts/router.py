from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request

from aivee_api.alerts.audit import AuditWriter, get_audit_writer, going_ro
from aivee_api.alerts.auth import AckAccess, ViewAccess
from aivee_api.alerts.schemas import (
    AlertView,
    ServiceHeatmap,
    ServiceMetrics,
    VerificationMetrics,
)
from aivee_api.alerts.service import (
    acknowledge,
    list_alerts,
    service_heatmap,
    service_metrics,
    verification_metrics,
)
from aivee_api.deps import ServicesDep, SessionDep
from aivee_api.push.router import get_vapid
from aivee_api.push.sender import PushMessage, PushSender, WebPushSender
from aivee_api.push.service import push_to_location

router = APIRouter(tags=["alerts"])

AuditDep = Annotated[AuditWriter, Depends(get_audit_writer)]
StateFilter = Literal["opened", "acknowledged", "arrived", "closed", "open"]


ACK_PUSH_TITLE = "AiVee · Preluată"


def _push_sender(request: Request) -> PushSender | None:
    """`app.state.push_sender` (tests), else a VAPID sender, else None (push not set up)."""
    sender: PushSender | None = getattr(request.app.state, "push_sender", None)
    if sender is not None:
        return sender
    vapid = get_vapid(request)
    return WebPushSender(vapid) if vapid.enabled else None


@router.post("/api/alerts/{event_id}/ack")
async def ack_alert(
    event_id: str,
    request: Request,
    s: SessionDep,
    services: ServicesDep,
    access: AckAccess,
    audit: AuditDep,
    background: BackgroundTasks,
    location_id: str | None = None,
) -> AlertView:
    view = await acknowledge(s, access, event_id, audit, location_id)
    sender = _push_sender(request)
    if sender is not None and view.location_id is not None:
        # Same tag as the alert's push: every phone's notification is replaced (silently,
        # the service worker does not renotify) by who is going. After the response.
        message = PushMessage(
            title=ACK_PUSH_TITLE, body=going_ro(view), kind="ack", url="/alerte", tag=view.event_id
        )
        background.add_task(push_to_location, services.sessions, sender, message, view.location_id)
    return view


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


@router.get("/api/metrics/service/heatmap", response_model_by_alias=True)
async def get_service_heatmap(
    s: SessionDep,
    access: ViewAccess,
    location_id: str | None = None,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
) -> ServiceHeatmap:
    """Alert count and median wait per weekday x hour (Europe/Bucharest); team level only."""
    return await service_heatmap(s, access, location_id, start, end)


@router.get("/api/metrics/verification")
async def get_verification_metrics(
    s: SessionDep, access: ViewAccess, location_id: str | None = None
) -> VerificationMetrics:
    """Verified alerts per rule and status (VERIFY_ALERTS)."""
    return await verification_metrics(s, access, location_id)
