import asyncio
import contextlib
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from aivee_api.deps import ServicesDep, SessionDep
from aivee_api.events.schemas import EventOut
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
    """Pushes {type: 'alert'|'suggestion', data} for every new row after the connection."""
    await ws.accept()
    feed = LiveFeed(ws.app.state.services.sessions)
    await feed.start()
    interval: float = getattr(ws.app.state, "ws_poll_interval_s", POLL_INTERVAL_S)

    async def push() -> None:
        while True:
            for message in await feed.poll():
                await ws.send_text(message.model_dump_json())
            await asyncio.sleep(interval)

    pusher = asyncio.create_task(push())
    try:
        while True:  # we never expect client messages; this only notices the disconnect
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        pusher.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await pusher
