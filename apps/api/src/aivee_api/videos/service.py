"""Store an uploaded clip and give it a virtual camera with a live camera's zones and rules."""

import uuid
from datetime import datetime
from pathlib import Path

from aivee_contracts.geometry import CameraConfig
from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.alerts.repository import AlertRepository
from aivee_api.auth.principal import Principal
from aivee_api.db.models import EventRow, VideoUploadRow
from aivee_api.db.repositories import (
    CameraRepository,
    DeviceRepository,
    RuleRepository,
    camera_config,
)
from aivee_api.errors import Invalid, NotFound
from aivee_api.videos.kind import UPLOAD_CAMERA_PREFIX
from aivee_api.videos.schemas import VideoAlert, VideoOut

EXTENSIONS = {".mp4", ".mov", ".webm"}
CONTENT_TYPES = {"video/mp4", "video/quicktime", "video/webm", "application/octet-stream", ""}
CHUNK = 1024 * 1024
BAD_TYPE_RO = "Fișierul trebuie să fie un video mp4, mov sau webm."
EMPTY_RO = "Fișierul este gol."


def too_big_ro(max_bytes: int) -> str:
    return f"Fișierul depășește {max_bytes // (1024 * 1024)} MB."


def too_long_ro(duration_s: float, max_s: float) -> str:
    minutes, seconds = divmod(round(duration_s), 60)
    return (
        f"Clipul are {minutes}:{seconds:02d}; se pot analiza cel mult {round(max_s / 60)} minute."
    )


def check_type(filename: str, content_type: str | None) -> str:
    """The lower-case extension of an accepted clip, else 422."""
    ext = Path(filename).suffix.lower()
    if ext not in EXTENSIONS or (content_type or "") not in CONTENT_TYPES:
        raise Invalid(BAD_TYPE_RO)
    return ext


async def save_upload(file: UploadFile, dest: Path, max_bytes: int) -> int:
    """Copy the upload to `dest` in chunks; 422 (and nothing kept) above `max_bytes`."""
    size = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise Invalid(too_big_ro(max_bytes))
                out.write(chunk)
        if size == 0:
            raise Invalid(EMPTY_RO)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return size


def new_upload_id() -> str:
    return uuid.uuid4().hex[:8]


def clip_camera_name(filename: str) -> str:
    return f"Clip {filename}"[:120]


async def create_upload(
    s: AsyncSession,
    p: Principal,
    *,
    upload_id: str,
    location_id: str,
    device_id: str,
    path: Path,
    filename: str,
    size_bytes: int,
    rotate: int,
    source_camera_id: str | None,
) -> VideoUploadRow:
    """The upload row, its device (offline until the run), and camera `video-<id>` with a
    copy of the source camera's zones and rules (new rule ids, same zone ids and tags)."""
    cameras, rules = CameraRepository(s), RuleRepository(s)
    zones = []
    copied = []
    camera_id = f"{UPLOAD_CAMERA_PREFIX}{upload_id}"
    if source_camera_id is not None:
        source = await cameras.get(source_camera_id)
        if source is None:
            raise NotFound(f"Camera {source_camera_id} nu există.")
        zones = camera_config(source).zones
        copied = [
            r.model_copy(update={"id": f"{upload_id}-{r.id}"[:64], "camera_id": camera_id})
            for r in await rules.for_camera(source_camera_id)
        ]
    await DeviceRepository(s).ensure_device(location_id, device_id)
    camera = CameraConfig(
        id=camera_id, name=clip_camera_name(filename), source=str(path), zones=zones
    )
    await cameras.upsert(camera, device_id)
    for rule in copied:
        await rules.upsert(rule)
    row = VideoUploadRow(
        id=upload_id,
        location_id=location_id,
        camera_id=camera_id,
        device_id=device_id,
        source_camera_id=source_camera_id,
        filename=filename,
        path=str(path),
        size_bytes=size_bytes,
        rotate=rotate,
        status="queued",
        progress=0.0,
        events=0,
        created_by_id=p.user_id,
        created_by_name=p.name,
    )
    s.add(row)
    await s.flush()
    await s.refresh(row)
    return row


async def alert_counts(s: AsyncSession, camera_ids: list[str]) -> dict[str, int]:
    if not camera_ids:
        return {}
    rows = await s.execute(
        select(EventRow.camera_id, func.count())
        .where(EventRow.camera_id.in_(camera_ids), EventRow.state == "opened")
        .group_by(EventRow.camera_id)
    )
    return {camera: int(n) for camera, n in rows.all()}


async def video_out(s: AsyncSession, row: VideoUploadRow) -> VideoOut:
    counts = await alert_counts(s, [row.camera_id])
    return VideoOut.of(row, counts.get(row.camera_id, 0))


async def list_uploads(s: AsyncSession, location_id: str, limit: int = 50) -> list[VideoOut]:
    rows = (
        await s.scalars(
            select(VideoUploadRow)
            .where(VideoUploadRow.location_id == location_id)
            .order_by(VideoUploadRow.created_at.desc(), VideoUploadRow.id)
            .limit(limit)
        )
    ).all()
    counts = await alert_counts(s, [r.camera_id for r in rows])
    return [VideoOut.of(r, counts.get(r.camera_id, 0)) for r in rows]


async def timeline(s: AsyncSession, row: VideoUploadRow, limit: int = 500) -> list[VideoAlert]:
    """The clip's alerts, earliest first, at their positions in the clip."""
    epoch: datetime | None = row.clip_epoch
    if epoch is None:
        return []
    views = await AlertRepository(s).views(camera_ids=[row.camera_id], limit=limit)
    return sorted((VideoAlert.of(v, epoch) for v in views), key=lambda a: a.at_s)
