"""End to end, offline: upload a synthetic clip through the API, the real edge runs on it as
a subprocess with the upload MQTT login (production ACL), ingest stores its alert, and the
timeline shows it at its clip position; nobody is notified.

Needs Docker and the edge models in `models/` (skipped without them). The clip is
ultralytics' bus.jpg (four people) panning, as in tools/bench_edge.py.
"""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from aivee_api.db.repositories import CameraRepository, DeviceRepository, RuleRepository
from aivee_api.deps import Services
from aivee_api.edge.publisher import MqttEdgeLink
from aivee_api.edge.sync import EdgeSync
from aivee_api.metrics.cache import MetricsCache
from aivee_api.push.sender import PushKind
from aivee_api.settings import ApiSettings
from aivee_api.videos.runner import EdgeClipProcess, VideoQueue
from aivee_contracts.events import AlertEvent
from aivee_contracts.geometry import CameraConfig, Zone
from aivee_contracts.rules import Action, Condition, Rule
from aivee_ingest.config import IngestSettings
from aivee_ingest.handler import IngestHandler
from aivee_ingest.worker import run_worker

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]
MODELS = REPO / "models"
DETECTOR = MODELS / "yolo11n_int8_openvino_model"
YUNET = MODELS / "face_detection_yunet_2023mar.onnx"
CLIP_S = 4

needs_models = pytest.mark.skipif(
    not (DETECTOR.exists() and YUNET.exists()), reason="edge models not downloaded"
)

WHOLE_FRAME = Zone.model_validate(
    {"id": "t1", "name": "Masa 1", "tag": "table", "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]}
)


class Notifier:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        self.calls.append(event.event_id)

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None, kind: PushKind
    ) -> None:
        self.calls.append(text)


def make_clip(path: Path, seconds: int = CLIP_S, fps: int = 25) -> Path:
    import cv2
    import numpy as np
    import ultralytics

    src = cv2.imread(str(Path(ultralytics.__file__).parent / "assets" / "bus.jpg"))
    w = src.shape[1]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (640, 480))
    n = seconds * fps
    for i in range(n):
        dx = int((w - 640 * 1.2) * (0.5 + 0.5 * np.sin(2 * np.pi * i / n)))
        writer.write(cv2.resize(src[: int(480 * 1.6), dx : dx + int(640 * 1.2)], (640, 480)))
    writer.release()
    return path


@pytest.fixture
def settings(tmp_path: Path, broker: Any) -> ApiSettings:
    return ApiSettings(
        site="test",
        device="edge-01",
        snapshot_dir=tmp_path / "snapshots",
        video_dir=tmp_path / "videos",
        mqtt_host=broker.host,
        mqtt_port=broker.port,
        mqtt_api_user=broker.api[0],
        mqtt_api_password=broker.api[1],
        mqtt_upload_user=broker.upload[0],
        mqtt_upload_password=broker.upload[1],
    )


@pytest.fixture
def notifier() -> "Notifier":
    return Notifier()


@pytest.fixture
async def services(
    notifier: "Notifier",
    settings: ApiSettings,
    sessions: Any,
    translator: Any,
    services_factory: Any,
    broker: Any,
    tmp_path: Path,
) -> AsyncIterator[Services]:
    link = MqttEdgeLink(settings, MetricsCache())
    link_task = asyncio.create_task(link.run())
    await asyncio.wait_for(link.connected.wait(), 10)
    svc: Services = services_factory(settings, sessions, link, translator)
    svc.sync = EdgeSync(sessions, link, settings.site, settings.device)
    handler = IngestHandler(sessions, settings.snapshot_dir, notifier)
    ingest = IngestSettings(
        mqtt_host=broker.host,
        mqtt_port=broker.port,
        mqtt_ingest_user=broker.ingest[0],
        mqtt_ingest_password=broker.ingest[1],
        mqtt_client_id=f"ingest-video-{uuid.uuid4().hex[:6]}",
    )
    ready = asyncio.Event()
    ingest_task = asyncio.create_task(run_worker(ingest, handler, ready))
    await asyncio.wait_for(ready.wait(), 10)
    queue = VideoQueue(sessions, svc.sync, EdgeClipProcess(settings), settle_s=1.0)
    await queue.start()
    svc.videos = queue
    yield svc
    await queue.stop()
    for task in (ingest_task, link_task):
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@needs_models
async def test_a_clip_runs_through_the_real_edge_and_shows_its_alert(
    services: Services,
    notifier: Notifier,
    sessions: Any,
    tenancy_factory: Any,
    client_factory: Any,
    login: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = services
    monkeypatch.chdir(REPO)  # the edge resolves models/ relative to its working dir
    monkeypatch.setenv("APPEARANCE", "false")
    await tenancy_factory(sessions)
    async with sessions() as s:
        await DeviceRepository(s).ensure_device("test", "edge-01")
        await CameraRepository(s).upsert(
            CameraConfig(id="cam1", name="Sala", source="rtsp://x", zones=[WHOLE_FRAME]),
            "edge-01",
        )
        await RuleRepository(s).upsert(
            Rule(
                id="r-cam1",
                camera_id="cam1",
                name="Oaspeți la masă",
                prompt_ro="Anunță-mă când stau oaspeți la masă",
                zone_tag="table",
                all_of=[Condition(kind="present", role="guest", min_duration_s=1)],
                action=Action(type="telegram"),
                cooldown_s=600,
            )
        )
        await s.commit()

    clip = make_clip(tmp_path / "bus.mp4")
    c = client_factory()
    await login(c, "manager@t.ro")
    r = await c.post(
        "/api/videos",
        files={"file": ("bus.mp4", clip.read_bytes(), "video/mp4")},
        data={"location_id": "test", "copy_from_camera_id": "cam1"},
    )
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    await asyncio.wait_for(svc.videos.drain(), 240)  # type: ignore[union-attr]

    video = (await c.get(f"/api/videos/{vid}")).json()
    log = (svc.settings.video_dir / f"{vid}.log").read_text(errors="replace")
    assert video["status"] == "done", (video, log[-2000:])
    assert video["duration_s"] == pytest.approx(CLIP_S, abs=0.2)
    assert video["events"] >= 1, log[-2000:]
    events = (await c.get(f"/api/videos/{vid}/events")).json()
    first = events[0]
    assert 0.9 <= first["at_s"] <= CLIP_S  # opened after the rule's 1 s, at its clip position
    assert first["zone_name"] == "Masa 1"
    assert events[-1]["state"] == "closed"
    assert notifier.calls == []  # the shift's phones stayed silent
    assert (await c.get("/api/alerts")).json() == []
    await c.aclose()
