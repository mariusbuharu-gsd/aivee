"""End to end: dashboard API → retained config → fake edge → Mosquitto → ingest → Postgres
→ API `/api/events`, `/ws/events` and `/api/snapshots/{id}`.

Everything runs in one event loop: the API under a real uvicorn server (so the websocket is
a real one), ingest's worker, and the fake edge's blocking pipeline in a thread.
"""

import asyncio
import contextlib
import importlib.util
import json
import socket
import sys
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
import uvicorn
import websockets
from aivee_api.deps import Services
from aivee_api.edge.publisher import MqttEdgeLink
from aivee_api.edge.sync import EdgeSync, LoggingEdgeCommands
from aivee_api.main import create_app
from aivee_api.metrics.cache import MetricsCache
from aivee_api.settings import ApiSettings
from aivee_contracts.events import AlertEvent
from aivee_edge.adapters.mqtt import MqttEdgeClient
from aivee_ingest.config import IngestSettings
from aivee_ingest.handler import IngestHandler
from aivee_ingest.worker import run_worker

pytestmark = pytest.mark.integration

TOOL = Path(__file__).resolve().parents[3] / "tools" / "fake_edge.py"


def _fake_edge() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fake_edge_e2e", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["fake_edge_e2e"] = module
    spec.loader.exec_module(module)
    return module


fake_edge = _fake_edge()


def _zone(zone_id: str, name: str, tag: str, x: float, y: float, size: float = 0.15) -> Any:
    return {
        "id": zone_id,
        "name": name,
        "tag": tag,
        "polygon": [[x, y], [x + size, y], [x + size, y + size], [x, y + size]],
    }


ZONES = [
    _zone("masa-geam", "Masa de la geam", "table", 0.05, 0.30),
    _zone("masa-bar", "Masa de la bar", "table", 0.75, 0.30),
    _zone("masa-colt", "Masa din colț", "table", 0.05, 0.75),
    _zone("bar", "Bar", "staff", 0.45, 0.80),
]
UNATTENDED = {
    "camera_id": "cam-sala",
    "name": "Masă neservită",
    "zone_tag": "table",
    "all_of": [
        {"kind": "present", "role": "guest", "min_duration_s": 60},
        {"kind": "absent", "role": "staff", "min_duration_s": 60},
    ],
    "cooldown_s": 300,
}


class QuietNotifier:
    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None: ...


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


async def _until(cond: Callable[[], Awaitable[bool]], timeout: float = 15) -> None:
    async def poll() -> None:
        while not await cond():
            await asyncio.sleep(0.1)

    await asyncio.wait_for(poll(), timeout)


@dataclass
class Stack:
    base_url: str
    http: httpx.AsyncClient
    edge: MqttEdgeClient
    snapshots: Path
    device: str


@pytest.fixture
async def stack(broker: Any, sessions: Any, site: str, tmp_path: Path) -> AsyncIterator[Stack]:
    device = broker.edge[0]
    snapshots = tmp_path / "data" / "snapshots"  # one dir, as in compose + `make api`
    tasks: list[asyncio.Task[Any]] = []

    # ingest
    ingest_ready = asyncio.Event()
    handler = IngestHandler(sessions, snapshots, QuietNotifier())
    ingest = IngestSettings(
        mqtt_host=broker.host,
        mqtt_port=broker.port,
        mqtt_ingest_user=broker.ingest[0],
        mqtt_ingest_password=broker.ingest[1],
        mqtt_client_id=f"ingest-e2e-{uuid.uuid4().hex[:6]}",
    )
    tasks.append(asyncio.create_task(run_worker(ingest, handler, ingest_ready)))

    # API with its real MQTT link, served by uvicorn
    settings = ApiSettings(
        site=site,
        device=device,
        mqtt_host=broker.host,
        mqtt_port=broker.port,
        mqtt_api_user=broker.api[0],
        mqtt_api_password=broker.api[1],
        snapshot_dir=snapshots,
    )
    link = MqttEdgeLink(settings, MetricsCache())
    sync = EdgeSync(sessions, link, site, device)
    link.on_connect = sync.publish_all
    tasks.append(asyncio.create_task(link.run()))
    services = Services(
        settings=settings,
        sessions=sessions,
        sync=sync,
        translator=None,  # type: ignore[arg-type]  # not used here
        commands=LoggingEdgeCommands(),
    )
    app = create_app(services)
    app.state.ws_poll_interval_s = 0.1
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    tasks.append(asyncio.create_task(server.serve()))

    edge = MqttEdgeClient(broker.host, broker.port, device, broker.edge[1], site, device)
    try:
        await asyncio.wait_for(ingest_ready.wait(), 10)
        await asyncio.wait_for(link.connected.wait(), 10)
        while not server.started:
            await asyncio.sleep(0.05)
        await asyncio.to_thread(edge.start)
        base_url = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient(base_url=base_url) as http:
            yield Stack(base_url, http, edge, snapshots, device)
    finally:
        await asyncio.to_thread(edge.stop)
        server.should_exit = True
        for t in tasks[:-1]:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t


async def test_fake_edge_alert_reaches_events_and_the_websocket(stack: Stack) -> None:
    r = await stack.http.post(
        "/api/cameras", json={"id": "cam-sala", "name": "Sala", "source": "fake", "zones": ZONES}
    )
    assert r.status_code == 201, r.text
    rule = await stack.http.post("/api/rules", json=UNATTENDED)
    assert rule.status_code == 201, rule.text
    rule_id = rule.json()["id"]

    async def edge_has_config() -> bool:
        config = stack.edge.device_config()
        return bool(config and config.cameras) and bool(stack.edge.rules())

    await _until(edge_has_config)
    camera = fake_edge.pick_camera(stack.edge.device_config(), None)
    assert camera is not None and camera.id == "cam-sala"
    layout = fake_edge.Layout.from_camera(camera)

    ws_url = stack.base_url.replace("http", "ws", 1) + "/ws/events"
    async with websockets.connect(ws_url) as ws:
        await asyncio.sleep(0.3)  # the feed's cursor starts at connect
        rec = await asyncio.to_thread(
            fake_edge.run_scenario,
            fake_edge.SCENARIOS["unattended"],
            stack.edge,
            fake_edge.FallbackConfig(stack.edge, camera.id, force_demo=False, layout=layout),
            device=stack.device,
            camera_id=camera.id,
            speed=500,
            layout=layout,
        )
        published = [(e.event_id, e.state) for e in rec.alerts]
        assert [s for _, s in published] == ["opened", "closed"]

        pushed: list[dict[str, Any]] = []
        deadline = time.monotonic() + 15
        while len(pushed) < 2 and time.monotonic() < deadline:
            message = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if message["type"] == "alert":
                pushed.append(message["data"])

    expected = {(eid, state, rule_id, "cam-sala", "masa-geam") for eid, state in published}
    got = {(e["event_id"], e["state"], e["rule_id"], e["camera_id"], e["zone_id"]) for e in pushed}
    assert got == expected

    events = (await stack.http.get("/api/events")).json()
    stored = {(e["event_id"], e["state"], e["zone_id"], e["device_id"]) for e in events}
    assert stored == {(eid, s, "masa-geam", stack.device) for eid, s in published}


async def test_snapshot_published_with_an_event_is_served_by_the_api(stack: Stack) -> None:
    jpeg = b"\xff\xd8\xff\xe0" + uuid.uuid4().bytes + b"\xff\xd9"
    event = AlertEvent(
        event_id=f"ev-{uuid.uuid4().hex[:12]}",
        rule_id="r1",
        camera_id="cam-sala",
        zone_id="masa-geam",
        state="opened",
        at=datetime.now(UTC),
        summary_ro="Masa de la geam așteaptă",
        snapshot=True,
    )
    await asyncio.to_thread(stack.edge.publish_alert, event, jpeg)

    async def served() -> bool:
        r = await stack.http.get(f"/api/snapshots/{event.event_id}")
        return r.status_code == 200

    await _until(served)
    r = await stack.http.get(f"/api/snapshots/{event.event_id}")
    assert r.headers["content-type"] == "image/jpeg" and r.content == jpeg
    [stored] = [
        e for e in (await stack.http.get("/api/events")).json() if e["event_id"] == event.event_id
    ]
    assert stored["snapshot_url"]
    assert (stack.snapshots / f"{event.event_id}.jpg").read_bytes() == jpeg
