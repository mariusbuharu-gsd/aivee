"""Analiză video: upload validation and permissions, the virtual camera with a live camera's
zones and rules, status transitions with a fake runner, and clips kept out of everything
the shift sees (alerts, live feed, service metrics, cameras, rules)."""

import json
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from aivee_api.alerts.repository import AlertRepository
from aivee_api.audit.models import AuditRow
from aivee_api.db.repositories import (
    CameraRepository,
    DeviceRepository,
    EventRepository,
    RuleRepository,
)
from aivee_api.deps import Services
from aivee_api.edge.publisher import RecordingPublisher
from aivee_api.settings import ApiSettings
from aivee_api.videos.probe import UnreadableVideo
from aivee_api.videos.runner import ClipJob, ClipResult, Progress, VideoQueue
from aivee_contracts.events import AlertEvent
from aivee_contracts.geometry import CameraConfig, Zone
from aivee_contracts.rules import Action, Condition, Rule
from aivee_contracts.topics import Topics
from sqlalchemy import select

pytestmark = pytest.mark.integration

TABLE = Zone.model_validate(
    {"id": "t1", "name": "Masa 1", "tag": "table", "polygon": [[0, 0], [0.3, 0], [0.3, 0.3]]}
)
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


class FakeClip:
    """Plays the part of the edge + ingest: stores the clip's events at clip positions."""

    def __init__(self, sessions: Any, *, ok: bool = True, duration_s: float = 95.0) -> None:
        self._sessions = sessions
        self.ok = ok
        self.duration_s = duration_s
        self.jobs: list[ClipJob] = []
        self.progress: list[float] = []

    async def run(self, job: ClipJob, progress: Progress) -> ClipResult:
        self.jobs.append(job)
        script = [
            ("a1", "opened", 12.0),
            ("a1-arr", "arrived", 31.0),
            ("a1-cl", "closed", 40.0),
            ("a2", "opened", 70.5),  # still open when the clip ends
        ]
        async with self._sessions() as s:
            for event_id, state, at_s in script:
                event = AlertEvent.model_validate(
                    {
                        "event_id": f"{job.upload_id}-{event_id}",
                        "rule_id": f"{job.upload_id}-r-cam1",
                        "camera_id": job.camera_id,
                        "zone_id": "t1",
                        "state": state,
                        "at": job.clip_epoch + timedelta(seconds=at_s),
                        "summary_ro": "Masa 1: neservită de 1 min",
                    }
                )
                await EventRepository(s).insert_if_new(event, job.device_id)
                await AlertRepository(s).link(event, job.device_id)
            await s.commit()
        for share in (0.5, 1.0):
            self.progress.append(share)
            await progress(share, self.duration_s)
        if not self.ok:
            return ClipResult(False, self.duration_s, "Serverul MQTT nu răspunde.")
        return ClipResult(True, self.duration_s)


@pytest.fixture
def settings(tmp_path: Path) -> ApiSettings:
    return ApiSettings(
        site="test",
        device="edge-01",
        snapshot_dir=tmp_path / "snapshots",
        video_dir=tmp_path / "videos",
        mqtt_enabled=False,
        mqtt_upload_user="upload-01",
        mqtt_upload_password="pw",
    )


@pytest.fixture
def clip(sessions: Any) -> FakeClip:
    return FakeClip(sessions)


@pytest.fixture
async def services(
    settings: ApiSettings,
    sessions: Any,
    publisher: RecordingPublisher,
    translator: Any,
    services_factory: Any,
    clip: FakeClip,
) -> AsyncIterator[Services]:
    svc: Services = services_factory(settings, sessions, publisher, translator)
    queue = VideoQueue(sessions, svc.sync, clip, settle_s=0.05)
    await queue.start()
    svc.videos = queue
    svc.video_probe = lambda _path: 95.0
    yield svc
    await queue.stop()


@pytest.fixture
async def world(sessions: Any, tenancy_factory: Any) -> None:
    """`test`: edge-01 with cam1 (zone Masa 1, one rule) and a live open alert."""
    await tenancy_factory(sessions)
    async with sessions() as s:
        await DeviceRepository(s).ensure_device("test", "edge-01")
        await CameraRepository(s).upsert(
            CameraConfig(id="cam1", name="Sala", source="rtsp://x", zones=[TABLE]), "edge-01"
        )
        await RuleRepository(s).upsert(
            Rule(
                id="r-cam1",
                camera_id="cam1",
                name="Masă neservită",
                prompt_ro="Anunță-mă dacă nimeni nu vine la masă",
                zone_tag="table",
                all_of=[Condition(kind="present", role="guest", min_duration_s=60)],
                action=Action(type="telegram"),
            )
        )
        await s.commit()


async def _as(client_factory: Any, login: Any, email: str) -> httpx.AsyncClient:
    c: httpx.AsyncClient = client_factory()
    await login(c, email)
    return c


async def _upload(
    c: httpx.AsyncClient,
    name: str = "sala-1.mp4",
    data: bytes = MP4,
    content_type: str = "video/mp4",
    **fields: str,
) -> httpx.Response:
    form = {"location_id": "test", "copy_from_camera_id": "cam1", **fields}
    return await c.post("/api/videos", files={"file": (name, data, content_type)}, data=form)


async def test_only_managers_of_the_location_may_upload(
    world: None, client_factory: Any, login: Any, settings: ApiSettings
) -> None:
    staff = await _as(client_factory, login, "staff@t.ro")
    r = await _upload(staff)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "forbidden"
    assert (await staff.get("/api/videos?location_id=test")).status_code == 403
    xowner = await _as(client_factory, login, "owner@x.ro")
    assert (await _upload(xowner)).status_code == 404
    assert not any(settings.video_dir.glob("*")) if settings.video_dir.exists() else True
    for c in (staff, xowner):
        await c.aclose()


async def test_upload_validation(
    world: None, client_factory: Any, login: Any, services: Services, settings: ApiSettings
) -> None:
    c = await _as(client_factory, login, "manager@t.ro")
    r = await _upload(c, name="notes.txt", content_type="text/plain")
    assert r.status_code == 422 and "mp4, mov sau webm" in r.json()["detail"]["message_ro"]
    r = await _upload(c, name="clip.avi", content_type="video/x-msvideo")
    assert r.status_code == 422
    r = await _upload(c, data=b"")
    assert r.status_code == 422 and r.json()["detail"]["message_ro"] == "Fișierul este gol."
    r = await _upload(c, rotate="45")
    assert r.status_code == 422
    r = await _upload(c, copy_from_camera_id="nope")
    assert r.status_code == 404

    settings.video_max_bytes = 10
    r = await _upload(c)
    assert r.status_code == 422 and "MB" in r.json()["detail"]["message_ro"]
    settings.video_max_bytes = 200 * 1024 * 1024

    services.video_probe = lambda _path: 150.0
    r = await _upload(c)
    assert r.status_code == 422 and "2:30" in r.json()["detail"]["message_ro"]

    def unreadable(path: Path) -> float | None:
        raise UnreadableVideo(str(path))

    services.video_probe = unreadable
    r = await _upload(c)
    assert r.status_code == 422 and "nu este un video" in r.json()["detail"]["message_ro"]
    assert list(settings.video_dir.glob("*")) == []  # nothing kept from refused uploads
    assert (await c.get("/api/videos?location_id=test")).json() == []
    await c.aclose()


async def test_clip_gets_a_virtual_camera_with_the_live_cameras_zones_and_rules(
    world: None,
    client_factory: Any,
    login: Any,
    sessions: Any,
    publisher: RecordingPublisher,
    services: Services,
    clip: FakeClip,
) -> None:
    c = await _as(client_factory, login, "manager@t.ro")
    r = await _upload(c, rotate="90")
    assert r.status_code == 201, r.text
    video = r.json()
    vid = video["id"]
    assert video["camera_id"] == f"video-{vid}"
    assert video["source_camera_id"] == "cam1"
    assert video["rotate"] == 90 and video["created_by"]["name"] == "Mihai"
    assert video["status"] in {"queued", "running", "done"}

    await services.videos.drain()  # type: ignore[union-attr]
    async with sessions() as s:
        camera = await CameraRepository(s).get(f"video-{vid}")
        assert camera is not None and camera.device_id == "upload-01"
        assert [z["name"] for z in camera.zones] == ["Masa 1"]
        rules = await RuleRepository(s).for_camera(f"video-{vid}")
        assert [(r.id, r.zone_tag, r.all_of) for r in rules] == [
            (f"{vid}-r-cam1", "table", [Condition(kind="present", role="guest", min_duration_s=60)])
        ]
        assert await RuleRepository(s).for_camera("cam1")  # the live rule stays

    # The runner's job: the upload device, the clip's camera, its rotation.
    (job,) = clip.jobs
    assert (job.device_id, job.camera_id, job.rotate, job.site) == (
        "upload-01",
        f"video-{vid}",
        90,
        "test",
    )
    # The upload device got its camera and rules as retained state before the run.
    topics = Topics(site="test", device="upload-01")
    config = publisher.last(topics.config)
    ruleset = publisher.last(topics.rules)
    assert config is not None and config.retain and ruleset is not None
    assert f"video-{vid}" in [cam["id"] for cam in json.loads(config.payload)["cameras"]]
    assert [r["id"] for r in json.loads(ruleset.payload)["rules"]] == [f"{vid}-r-cam1"]

    # Virtual cameras and their copied rules stay off the live pages.
    assert [cam["id"] for cam in (await c.get("/api/cameras")).json()] == ["cam1"]
    assert [r["id"] for r in (await c.get("/api/rules")).json()] == ["r-cam1"]
    assert [d["device"] for d in (await c.get("/api/devices")).json()] == ["edge-01"]
    await c.aclose()


async def test_analysis_runs_to_done_with_a_timeline_at_clip_positions(
    world: None,
    client_factory: Any,
    login: Any,
    sessions: Any,
    services: Services,
    clip: FakeClip,
) -> None:
    c = await _as(client_factory, login, "owner@t.ro")
    vid = (await _upload(c)).json()["id"]
    await services.videos.drain()  # type: ignore[union-attr]

    video = (await c.get(f"/api/videos/{vid}")).json()
    assert video["status"] == "done" and video["progress"] == 1.0
    assert video["duration_s"] == 95.0 and video["events"] == 2 and video["error_ro"] is None
    assert video["started_at"] is not None and video["finished_at"] is not None
    assert clip.progress == [0.5, 1.0]
    assert [v["id"] for v in (await c.get("/api/videos?location_id=test")).json()] == [vid]

    events = (await c.get(f"/api/videos/{vid}/events")).json()
    assert [(e["at_s"], e["state"], e["closed_reason"]) for e in events] == [
        (12.0, "closed", None),
        (70.5, "closed", "video_end"),
    ]
    first, last = events
    assert (first["arrived_at_s"], first["closed_at_s"], first["wait_s"]) == (31.0, 40.0, 19.0)
    assert first["zone_name"] == "Masa 1" and first["summary_ro"].startswith("Masa 1")
    assert last["closed_at_s"] == 95.0  # closed at the end of the clip

    # Nothing of the clip reaches what the shift sees.
    assert (await c.get("/api/alerts")).json() == []
    stats = (await c.get("/api/metrics/service")).json()
    assert stats["alerts"] == 0 and stats["wait"]["count"] == 0
    assert (await c.get("/api/events")).json() == []
    assert (await c.get("/api/metrics")).json()["events_today"] == 0

    async with sessions() as s:
        audit = (await s.scalars(select(AuditRow).order_by(AuditRow.id))).all()
    videos = [a for a in audit if a.kind.startswith("video.")]
    assert [(a.kind, a.actor_kind) for a in videos] == [
        ("video.uploaded", "user"),
        ("video.analysed", "system"),
    ]
    assert videos[0].summary_ro == "Olga a încărcat clipul sala-1.mp4 pentru analiză"
    assert videos[1].summary_ro == "Analiza clipului sala-1.mp4 s-a încheiat: 2 alerte"
    assert not [a for a in audit if a.kind.startswith("alert.")]
    await c.aclose()


async def test_a_failed_run_is_reported_and_its_alerts_closed(
    world: None, client_factory: Any, login: Any, services: Services, clip: FakeClip
) -> None:
    clip.ok = False
    c = await _as(client_factory, login, "manager@t.ro")
    vid = (await _upload(c)).json()["id"]
    await services.videos.drain()  # type: ignore[union-attr]
    video = (await c.get(f"/api/videos/{vid}")).json()
    assert video["status"] == "failed"
    assert video["error_ro"] == "Serverul MQTT nu răspunde."
    events = (await c.get(f"/api/videos/{vid}/events")).json()
    assert all(e["state"] == "closed" for e in events)
    other = await _as(client_factory, login, "other@t.ro")  # manager of another location
    assert (await other.get(f"/api/videos/{vid}")).status_code == 404
    for x in (c, other):
        await x.aclose()


async def test_upload_needs_the_runner_login(
    world: None, client_factory: Any, login: Any, settings: ApiSettings
) -> None:
    settings.mqtt_upload_password = ""
    c = await _as(client_factory, login, "manager@t.ro")
    r = await _upload(c)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "unavailable"
    await c.aclose()


async def test_capabilities_say_whether_clips_can_be_analysed(
    world: None, client_factory: Any, login: Any, settings: ApiSettings
) -> None:
    anon = client_factory()
    assert (await anon.get("/api/capabilities")).status_code == 401
    c = await _as(client_factory, login, "manager@t.ro")
    assert (await c.get("/api/capabilities")).json() == {"videos": True, "enrol": False}
    settings.mqtt_upload_password = ""
    assert (await c.get("/api/capabilities")).json()["videos"] is False
    for x in (anon, c):
        await x.aclose()


async def test_reserved_ids_cannot_be_used_by_live_cameras(
    world: None, client_factory: Any, login: Any
) -> None:
    c = await _as(client_factory, login, "manager@t.ro")
    r = await c.post("/api/cameras", json={"id": "video-x", "name": "X", "source": "rtsp://x"})
    assert r.status_code == 422
    r = await c.post("/api/cameras", json={"name": "X", "source": "rtsp://x", "device": "upload-9"})
    assert r.status_code == 422
    await c.aclose()
