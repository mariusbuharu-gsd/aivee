"""Analiză video: upload a short recorded clip, analyse it like a live camera, read its
alerts at their mm:ss in the clip. All routes need `devices.manage` at the location."""

from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from aivee_api.audit.record import record
from aivee_api.audit.repository import Target
from aivee_api.auth.deps import CurrentUser
from aivee_api.auth.permissions import DEVICES_MANAGE
from aivee_api.auth.principal import Principal
from aivee_api.auth.scope import authorize_at, camera_location
from aivee_api.db.models import VideoUploadRow
from aivee_api.deps import ServicesDep, SessionDep
from aivee_api.errors import Invalid, NotFound, Unavailable
from aivee_api.videos.kind import is_upload_device
from aivee_api.videos.probe import UnreadableVideo
from aivee_api.videos.schemas import VideoAlert, VideoOut
from aivee_api.videos.service import (
    check_type,
    create_upload,
    list_uploads,
    new_upload_id,
    save_upload,
    timeline,
    too_long_ro,
    video_out,
)

router = APIRouter(prefix="/api/videos", tags=["videos"])

ROTATIONS = (0, 90, 180, 270)
NO_LOCATION_RO = "Locația nu există."
MISSING_RO = "Clipul nu există."
OFF_RO = "Analiza video nu este pornită pe acest server."
NOT_HERE_RO = "Analiza video merge doar la locația conectată la acest server."
UNREADABLE_RO = "Fișierul nu este un video care poate fi citit."


def _location(p: Principal, location_id: str | None) -> str:
    loc = location_id or p.default_location()
    authorize_at(p, DEVICES_MANAGE, loc, NO_LOCATION_RO)
    return loc


async def _upload(s: SessionDep, p: Principal, upload_id: str) -> VideoUploadRow:
    row = await s.get(VideoUploadRow, upload_id)
    if row is None or p.role_at(row.location_id) is None:
        raise NotFound(MISSING_RO)
    authorize_at(p, DEVICES_MANAGE, row.location_id, MISSING_RO)
    return row


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_video(
    s: SessionDep,
    svc: ServicesDep,
    p: CurrentUser,
    file: Annotated[UploadFile, File(description="mp4, mov or webm; ≤ 200 MB, ≤ 2 min")],
    location_id: Annotated[str | None, Form(max_length=64)] = None,
    rotate: Annotated[int, Form()] = 0,
    copy_from_camera_id: Annotated[str | None, Form(max_length=64)] = None,
    location_query: Annotated[str | None, Query(alias="location_id", max_length=64)] = None,
) -> VideoOut:
    """Store the clip, give it camera `video-<id>` with the zones and rules of
    `copy_from_camera_id`, and queue it. It never notifies the staff."""
    loc = _location(p, location_id or location_query)
    settings = svc.settings
    if svc.videos is None or not settings.mqtt_upload_password:
        raise Unavailable(OFF_RO)
    if not is_upload_device(settings.mqtt_upload_user):
        raise Unavailable(OFF_RO)
    if loc != svc.sync.site:
        raise Invalid(NOT_HERE_RO)
    if rotate not in ROTATIONS:
        raise Invalid("Rotirea poate fi 0, 90, 180 sau 270 de grade.")
    source = copy_from_camera_id or None
    if source is not None and await camera_location(s, source) != loc:
        raise NotFound(f"Camera {source} nu există.")
    filename = (file.filename or "clip").rsplit("/", 1)[-1][:200]
    ext = check_type(filename, file.content_type)
    upload_id = new_upload_id()
    path = settings.video_dir / f"{upload_id}{ext}"
    size = await save_upload(file, path, settings.video_max_bytes)
    try:
        duration = svc.video_probe(path)
    except UnreadableVideo:
        path.unlink(missing_ok=True)
        raise Invalid(UNREADABLE_RO) from None
    if duration is not None and duration > settings.video_max_s + 0.5:
        path.unlink(missing_ok=True)
        raise Invalid(too_long_ro(duration, settings.video_max_s))
    row = await create_upload(
        s,
        p,
        upload_id=upload_id,
        location_id=loc,
        device_id=settings.mqtt_upload_user,
        path=path,
        filename=filename,
        size_bytes=size,
        rotate=rotate,
        source_camera_id=source,
    )
    row.duration_s = duration
    await s.commit()
    out = await video_out(s, row)
    await record(
        s,
        p,
        "video.uploaded",
        location_id=loc,
        target=Target("video", row.id, filename),
        after=out.model_dump(mode="json"),
        camera=source or "",
    )
    svc.videos.submit(row.id)
    return out


@router.get("")
async def list_videos(
    s: SessionDep,
    p: CurrentUser,
    location_id: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[VideoOut]:
    return await list_uploads(s, _location(p, location_id), limit)


@router.get("/{upload_id}")
async def get_video(upload_id: str, s: SessionDep, p: CurrentUser) -> VideoOut:
    return await video_out(s, await _upload(s, p, upload_id))


@router.get("/{upload_id}/events")
async def video_events(upload_id: str, s: SessionDep, p: CurrentUser) -> list[VideoAlert]:
    return await timeline(s, await _upload(s, p, upload_id))
