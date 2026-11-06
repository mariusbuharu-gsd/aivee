import asyncio
import contextlib
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from aivee_api.alerts.live import AlertFeed
from aivee_api.deps import Services, ServicesDep, SessionDep
from aivee_api.events.schemas import DetectionsMessage, EventOut
from aivee_api.events.service import LiveFeed, recent_events, snapshot_file

log = logging.getLogger(__name__)

router = APIRouter(tags=["events"])

POLL_INTERVAL_S = 1.0


@router.get("/api/events")
async def list_events(s: SessionDep, limit: int = Query(50, ge=1, le=500)) -> list[EventOut]:
    return await recent_events(s, limit)


@router.get("/api/snapshots/{event_id}", response_class=FileResponse)
async def get_snapshot(event_id: str, svc: ServicesDep) -> FileResponse:
    path = snapshot_file(svc.settings.snapshot_dir, event_id)
    return FileResponse(path, media_type="image/jpeg")


@router.websocket("/ws/events")
async def events_socket(ws: WebSocket) -> None:
    """Pushes {type: 'alert'|'suggestion', data} for every new row after the connection,
    {type: 'alert', data: AlertView} whenever an alert changes (incl. acknowledgement), and
    {type: 'detections', camera_id, data} for live boxes as they arrive from the edge."""
    await ws.accept()
    services: Services = ws.app.state.services
    feed = LiveFeed(services.sessions)
    alerts = AlertFeed(services.sessions)
    await feed.start()
    await alerts.start()
    interval: float = getattr(ws.app.state, "ws_poll_interval_s", POLL_INTERVAL_S)
    sending = asyncio.Lock()  # two producers, one socket

    async def send(message: BaseModel) -> None:
        async with sending:
            await ws.send_text(message.model_dump_json())

    async def push_rows() -> None:
        while True:
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
