"""Analyse uploaded clips one at a time with the real edge pipeline.

`VideoQueue` is started by the API's lifespan: an asyncio queue and one worker (concurrency
1: the edge uses every core it gets). For each clip it marks the upload running, publishes the
retained config and rules (so the upload device sees the clip's camera), runs a `ClipProcess`,
polls its progress, then closes the alerts still open at the end of the clip (`video_end`)
and marks the upload done or failed.

`EdgeClipProcess` runs `python -m aivee_edge --source <clip> --clip-epoch <start> ...` as a
subprocess under the upload device's MQTT login; tests pass a fake process.
"""

import asyncio
import contextlib
import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_api.alerts.repository import AlertRepository
from aivee_api.audit.repository import Actor, AuditRepository, Target
from aivee_api.db.models import EventRow, Site, VideoUploadRow
from aivee_api.edge.sync import EdgeSync
from aivee_api.settings import ApiSettings

log = logging.getLogger(__name__)

SYSTEM = Actor("system", "system", "AiVee")
RESTARTED_RO = "Serverul a repornit în timpul analizei. Încarcă clipul din nou."
TOO_LONG_RO = "Clipul e mai lung de 2 minute."
EXIT_RO = {
    2: "Modelele de analiză nu sunt instalate pe server.",
    3: "Serverul MQTT nu răspunde.",
    4: "Zonele și regulile camerei nu au ajuns la analiză.",
}


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ClipJob:
    upload_id: str
    path: Path
    site: str
    device_id: str
    camera_id: str
    rotate: int
    clip_epoch: datetime


@dataclass(frozen=True)
class ClipResult:
    ok: bool
    duration_s: float | None = None
    error_ro: str | None = None


Progress = Callable[[float, float | None], Awaitable[None]]
"""(share done 0..1, clip duration in seconds or None)."""


class ClipProcess(Protocol):
    async def run(self, job: ClipJob, progress: Progress) -> ClipResult: ...


def read_progress(path: Path) -> tuple[float, float | None] | None:
    """(position_s, duration_s) from the edge's progress file, None while it has none."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    duration = data.get("duration_s")
    return float(data.get("position_s", 0.0)), float(duration) if duration else None


class EdgeClipProcess:
    """The edge as a subprocess (`VIDEO_PYTHON -m aivee_edge`, no loop), as the upload
    device. Its log goes to `<VIDEO_DIR>/<id>.log`."""

    def __init__(self, settings: ApiSettings, poll_s: float = 1.0) -> None:
        self._settings = settings
        self._poll_s = poll_s

    def command(self, job: ClipJob, progress_file: Path) -> list[str]:
        s = self._settings
        return [
            s.video_python or sys.executable,
            "-m",
            "aivee_edge",
            "--source",
            str(job.path),
            "--camera-id",
            job.camera_id,
            "--rotate",
            str(job.rotate),
            "--fps",
            str(s.video_fps),
            "--clip-epoch",
            job.clip_epoch.isoformat(),
            "--progress-file",
            str(progress_file),
            "--wait-config",
            "20",
        ]

    def env(self, job: ClipJob) -> dict[str, str]:
        s = self._settings
        return {
            **os.environ,
            "MQTT_HOST": s.mqtt_host,
            "MQTT_PORT": str(s.mqtt_port),
            "MQTT_EDGE_USER": s.mqtt_upload_user,
            "MQTT_EDGE_PASSWORD": s.mqtt_upload_password,
            "SITE": job.site,
            "DEVICE": job.device_id,
            "LOOP_FILE": "false",
        }

    async def run(self, job: ClipJob, progress: Progress) -> ClipResult:
        s = self._settings
        progress_file = s.video_dir / f"{job.upload_id}.progress.json"
        progress_file.unlink(missing_ok=True)
        log_file = s.video_dir / f"{job.upload_id}.log"
        with log_file.open("wb") as out:
            proc = await asyncio.create_subprocess_exec(
                *self.command(job, progress_file),
                env=self.env(job),
                stdout=out,
                stderr=asyncio.subprocess.STDOUT,
            )
            duration: float | None = None
            too_long = False
            while proc.returncode is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(proc.wait(), self._poll_s)
                seen = read_progress(progress_file)
                if seen is None:
                    continue
                position, duration = seen
                if duration and duration > s.video_max_s + 1:
                    too_long = True
                    proc.terminate()
                    await proc.wait()
                    break
                await progress(min(1.0, position / duration) if duration else 0.0, duration)
        code = proc.returncode
        if too_long:
            return ClipResult(False, duration, TOO_LONG_RO)
        if code != 0:
            log.warning("clip %s: edge exited with %s (log %s)", job.upload_id, code, log_file)
            return ClipResult(
                False, duration, EXIT_RO.get(code or 0, f"Analiza a eșuat (cod {code}).")
            )
        return ClipResult(True, duration)


class VideoQueue:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        sync: EdgeSync,
        process: ClipProcess,
        *,
        settle_s: float = 3.0,
        settle_max_s: float = 30.0,
        now: Callable[[], datetime] = _now,
    ) -> None:
        self._sessions = sessions
        self._sync = sync
        self._process = process
        self._settle_s = settle_s
        self._settle_max_s = settle_max_s
        self._now = now
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    def submit(self, upload_id: str) -> None:
        self._queue.put_nowait(upload_id)

    async def start(self) -> None:
        """Fail what a previous process left running, queue again what it left queued."""
        async with self._sessions() as s:
            rows = (
                await s.scalars(
                    select(VideoUploadRow)
                    .where(VideoUploadRow.status.in_(("queued", "running")))
                    .order_by(VideoUploadRow.created_at)
                )
            ).all()
            for row in rows:
                if row.status == "running":
                    row.status, row.error_ro, row.finished_at = "failed", RESTARTED_RO, self._now()
                else:
                    self.submit(row.id)
            await s.commit()
        self._worker = asyncio.create_task(self._work())

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    async def drain(self) -> None:
        """Wait until every submitted clip is finished (tests)."""
        await self._queue.join()

    async def _work(self) -> None:
        while True:
            upload_id = await self._queue.get()
            try:
                await self.run_one(upload_id)
            except Exception:
                log.exception("clip %s: analysis crashed", upload_id)
                await self._finish(upload_id, ClipResult(False, None, "Analiza a eșuat."))
            finally:
                self._queue.task_done()

    async def run_one(self, upload_id: str) -> None:
        started = self._now()
        async with self._sessions() as s:
            row = await s.get(VideoUploadRow, upload_id)
            if row is None or row.status != "queued":
                return
            row.status, row.started_at, row.clip_epoch, row.progress = (
                "running",
                started,
                started,
                0,
            )
            job = ClipJob(
                upload_id=row.id,
                path=Path(row.path),
                site=row.location_id,
                device_id=row.device_id,
                camera_id=row.camera_id,
                rotate=row.rotate,
                clip_epoch=started,
            )
            await s.commit()
        # The upload device gets this clip's camera, zones and rules as retained state.
        await self._sync.publish_config()
        await self._sync.publish_rules()

        async def progress(share: float, duration_s: float | None) -> None:
            async with self._sessions() as s:
                row = await s.get(VideoUploadRow, upload_id)
                if row is not None:
                    row.progress = round(share, 3)
                    row.duration_s = duration_s or row.duration_s
                    await s.commit()

        log.info("clip %s: analysing %s as %s", upload_id, job.path.name, job.camera_id)
        result = await self._process.run(job, progress)
        if result.ok:
            await self._settle(job.camera_id)
        await self._finish(upload_id, result)

    async def _event_count(self, camera_id: str) -> int:
        async with self._sessions() as s:
            count = await s.scalar(
                select(func.count()).select_from(EventRow).where(EventRow.camera_id == camera_id)
            )
        return int(count or 0)

    async def _settle(self, camera_id: str) -> None:
        """Ingest stores the last events a moment after the edge exits: wait until the
        camera's event count stops changing for `settle_s` (at most `settle_max_s`)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._settle_max_s
        last, stable_since = await self._event_count(camera_id), loop.time()
        while loop.time() < deadline and loop.time() - stable_since < self._settle_s:
            await asyncio.sleep(min(0.5, self._settle_s))
            count = await self._event_count(camera_id)
            if count != last:
                last, stable_since = count, loop.time()

    async def _finish(self, upload_id: str, result: ClipResult) -> None:
        async with self._sessions() as s:
            row = await s.get(VideoUploadRow, upload_id)
            if row is None:
                return
            row.duration_s = result.duration_s or row.duration_s
            row.finished_at = self._now()
            if row.clip_epoch is not None:
                # Nothing closes an alert after the clip ends: the system does, at its end.
                end = (
                    row.clip_epoch + timedelta(seconds=row.duration_s)
                    if row.duration_s
                    else row.finished_at
                )
                await AlertRepository(s).close_open_for_camera(row.camera_id, end, "video_end")
            row.events = await count_alerts(s, row.camera_id)
            if result.ok:
                row.status, row.progress, row.error_ro = "done", 1.0, None
            else:
                row.status, row.error_ro = "failed", result.error_ro or "Analiza a eșuat."
            site = await s.get(Site, row.location_id)
            await AuditRepository(s).append(
                "video.analysed" if result.ok else "video.failed",
                SYSTEM,
                org_id=site.org_id if site else None,
                location_id=row.location_id,
                target=Target("video", row.id, row.filename),
                after={"status": row.status, "events": row.events, "error_ro": row.error_ro},
                count=str(row.events),
                error=row.error_ro or "",
            )
            await s.commit()
        log.info("clip %s: %s, %d alert(s)", upload_id, row.status, row.events)


async def count_alerts(s: AsyncSession, camera_id: str) -> int:
    count = await s.scalar(
        select(func.count())
        .select_from(EventRow)
        .where(EventRow.camera_id == camera_id, EventRow.state == "opened")
    )
    return int(count or 0)
