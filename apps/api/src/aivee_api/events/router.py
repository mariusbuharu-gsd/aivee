import asyncio
import contextlib
import logging
from datetime import timedelta
from typing import Annotated

from aivee_contracts.events import BEFORE_SUFFIX
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from aivee_api.alerts.live import AlertFeed
from aivee_api.auth.deps import COOKIE, Access, CurrentUser, require
from aivee_api.auth.permissions import ALERTS_VIEW, STAFF_REVIEW
from aivee_api.auth.principal import principal_for_token
from aivee_api.auth.scope import authorize_at, event_location, events_at, suggestion_location
from aivee_api.db.models import EventRow
from aivee_api.deps import Services, ServicesDep, SessionDep
from aivee_api.errors import NotFound
from aivee_api.events.schemas import DetectionsMessage, EventOut, event_out
from aivee_api.events.scope import LiveScope
from aivee_api.events.service import LEGACY_STATES, LiveFeed, snapshot_file

log = logging.getLogger(__name__)

router = APIRouter(tags=["events"])

POLL_INTERVAL_S = 1.0


@router.get("/api/events")
async def list_events(
    s: SessionDep,
    access: Annotated[Access, Depends(require(ALERTS_VIEW))],
    limit: int = Query(50, ge=1, le=500),
) -> list[EventOut]:
    stmt = (
        events_at(access.location_id)
        .where(EventRow.state.in_(LEGACY_STATES))  # `arrived` only reaches the dashboard folded
        .order_by(EventRow.at.desc())
        .limit(limit)
    )
    return [event_out(r) for r in await s.scalars(stmt)]


@router.get("/api/snapshots/{event_id}", response_class=FileResponse)
async def get_snapshot(
    event_id: str, p: CurrentUser, s: SessionDep, svc: ServicesDep
) -> FileResponse:
    """The blurred JPEG of an event (alerts.view) or of a staff suggestion (staff.review).
    `<event_id>-before` is the "before" image of an object change, with its event's rights."""
    missing = "Imaginea nu există."
    loc = await event_location(s, event_id.removesuffix(BEFORE_SUFFIX))
    if loc is not None:
        authorize_at(p, ALERTS_VIEW, loc, missing)
    else:
        loc = await suggestion_location(s, event_id)
        if loc is None:
            raise NotFound(missing)
        authorize_at(p, STAFF_REVIEW, loc, missing)
    path = snapshot_file(svc.settings.snapshot_dir, event_id)
    return FileResponse(path, media_type="image/jpeg")


async def authenticate_ws(ws: WebSocket, services: Services) -> LiveScope | None:
    """The session cookie of the handshake → what the socket may stream (None: reject)."""
    ttl = timedelta(hours=services.settings.session_ttl_hours)
    async with services.sessions() as s:
        found = await principal_for_token(s, ws.cookies.get(COOKIE), ttl)
    if found is None:
        return None
    p = found.principal
    return LiveScope(p.locations_with(ALERTS_VIEW), p.locations_with(STAFF_REVIEW))


@router.websocket("/ws/events")
async def events_socket(ws: WebSocket) -> None:
    """Pushes {type: 'alert'|'suggestion', data} for every new row after the connection,
    {type: 'alert', data: AlertView} whenever an alert changes (incl. acknowledgement), and
    {type: 'detections', camera_id, data} for live boxes as they arrive from the edge,
    limited to the locations of the user behind the `aivee_session` cookie (else closed
    with 1008)."""
    services: Services = ws.app.state.services
    scope = await authenticate_ws(ws, services)
    if scope is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="unauthenticated")
        return
    await ws.accept()
    await scope.refresh(services.sessions)
    feed = LiveFeed(services.sessions)
    alerts = AlertFeed(services.sessions, scope.alert_locations)
    await feed.start()
    await alerts.start()
    interval: float = getattr(ws.app.state, "ws_poll_interval_s", POLL_INTERVAL_S)
    sending = asyncio.Lock()  # two producers, one socket

    async def send(message: BaseModel) -> None:
        if not scope.allows(message):
            return
        async with sending:
            await ws.send_text(message.model_dump_json())

    async def push_rows() -> None:
        while True:
            await scope.refresh(services.sessions)
            for message in [*await feed.poll(), *await alerts.poll()]:
                await send(message)
            await asyncio.sleep(interval)

    async def push_detections(queue: asyncio.Queue[DetectionsMessage]) -> None:
        while True:
            await send(await queue.get())

    with services.live.subscribe() as queue:
        pushers = [
            asyncio.create_task(push_rows()),
            asyncio.create_task(push_detections(queue)),
        ]
        try:
            while True:  # we never expect client messages; this only notices the disconnect
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            for pusher in pushers:
                pusher.cancel()
            for pusher in pushers:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await pusher
