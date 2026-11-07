import asyncio
import base64
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Path, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.audit.record import record
from aivee_api.audit.repository import Target
from aivee_api.auth.deps import Access, CurrentUser, require
from aivee_api.auth.permissions import STAFF_ENROL, STAFF_REVIEW
from aivee_api.auth.principal import Principal
from aivee_api.auth.scope import authorize_at, authorize_camera, suggestion_location
from aivee_api.db.repositories import CameraRepository, SuggestionRepository
from aivee_api.deps import Services, ServicesDep, SessionDep
from aivee_api.errors import Invalid, NotFound, TooLarge, Unavailable
from aivee_api.events.schemas import SuggestionOut
from aivee_api.staff.capture import CAPTURE_TTL_S, SAMPLE_INTERVAL_S, sample_frames
from aivee_api.staff.enrol import Upload
from aivee_api.staff.schemas import (
    CaptureCandidate,
    CaptureConfirmIn,
    CaptureIn,
    CaptureOut,
    DecisionOut,
    EnrolOut,
    ProfileOut,
)
from aivee_api.staff.service import NO_ENROLLER, StaffService

router = APIRouter(prefix="/api/staff", tags=["staff"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
NO_FRAMES_RO = (
    "Camera nu trimite imagini acum. Pornește conectorul sau telefonul-cameră și încearcă din nou."
)
capture_sleep = asyncio.sleep
"""How the capture waits between samples (tests swap it for a fake clock)."""
MAX_PHONE_FRAMES = 30
MAX_PHONE_FRAME_BYTES = 2 * 1024 * 1024
CAPTURE_GONE_RO = "Captura a expirat sau nu există. Începe din nou."


def _service(s: AsyncSession, svc: Services) -> StaffService:
    return StaffService(s, svc.sync, svc.commands, svc.enroller, svc.settings.snapshot_dir)


ReviewAccess = Annotated[Access, Depends(require(STAFF_REVIEW))]
EnrolAccess = Annotated[Access, Depends(require(STAFF_ENROL))]


@router.get("/suggestions")
async def list_suggestions(
    s: SessionDep, svc: ServicesDep, access: ReviewAccess
) -> list[SuggestionOut]:
    pending = await _service(s, svc).pending_suggestions()
    return [
        x for x in pending if await suggestion_location(s, x.suggestion_id) == access.location_id
    ]


async def _decide(
    suggestion_id: str, confirmed: bool, s: AsyncSession, svc: Services, p: Principal
) -> DecisionOut:
    loc, _ = authorize_at(
        p,
        STAFF_REVIEW,
        await suggestion_location(s, suggestion_id),
        f"Sugestia {suggestion_id} nu există.",
    )
    row = await SuggestionRepository(s).get(suggestion_id)
    st = svc.settings
    out = await _service(s, svc).decide(
        suggestion_id, confirmed, st.default_profile_id, st.default_profile_name
    )
    camera_id = row.camera_id if row else ""
    camera = await CameraRepository(s).get(camera_id)
    await record(
        s,
        p,
        "staff.confirmed" if confirmed else "staff.rejected",
        location_id=loc,
        target=Target("camera", camera_id, camera.name if camera and camera.name else camera_id),
        after={"suggestion_id": suggestion_id, "status": out.status},
    )
    return out


@router.post("/suggestions/{suggestion_id}/confirm")
async def confirm_suggestion(
    suggestion_id: str, s: SessionDep, svc: ServicesDep, p: CurrentUser
) -> DecisionOut:
    return await _decide(suggestion_id, True, s, svc, p)


@router.post("/suggestions/{suggestion_id}/reject")
async def reject_suggestion(
    suggestion_id: str, s: SessionDep, svc: ServicesDep, p: CurrentUser
) -> DecisionOut:
    return await _decide(suggestion_id, False, s, svc, p)


@router.get("/profiles")
async def list_profiles(s: SessionDep, svc: ServicesDep, _: EnrolAccess) -> list[ProfileOut]:
    return await _service(s, svc).profiles()


@router.post("/photos")
async def upload_photos(
    s: SessionDep,
    svc: ServicesDep,
    access: EnrolAccess,
    photo: Annotated[list[UploadFile] | None, File(description="Images or a short video")] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
    profile_id: Annotated[str | None, Form(pattern=r"^[A-Za-z0-9_-]{1,64}$")] = None,
    name: Annotated[str | None, Form()] = None,
    description_ro: Annotated[str, Form()] = "",
) -> EnrolOut:
    """Enrol staff appearance from photos (field `photo` or `files`, repeatable)."""
    uploads = []
    for f in [*(photo or []), *(files or [])]:
        data = await f.read(MAX_UPLOAD_BYTES + 1)
        uploads.append(Upload(f.filename or "upload", f.content_type or "", data))
    oversized = [u.filename for u in uploads if len(u.data) > MAX_UPLOAD_BYTES]
    if oversized:
        raise Invalid(f"Fișier prea mare (max 50 MB): {', '.join(oversized)}")
    st = svc.settings
    out = await _service(s, svc).enrol(
        uploads,
        profile_id or st.default_profile_id,
        name or st.default_profile_name,
        description_ro,
    )
    await record(
        s,
        access.principal,
        "staff.enrolled",
        location_id=access.location_id,
        target=Target("staff_profile", out.profile.id, out.profile.name),
        after={"files": out.files, "examples_added": out.examples_added},
        count=str(out.examples_added),
    )
    return out


@router.post("/capture")
async def capture(body: CaptureIn, svc: ServicesDep, p: CurrentUser) -> CaptureOut:
    """Sample a cloud camera's live frames for `seconds` (one every ~1.5 s), keep the largest
    person of each, and hold the crops for `/capture/{token}/confirm`. The request lasts about
    `seconds`; no database session is held meanwhile."""
    async with svc.sessions() as s:
        loc = await authorize_camera(s, p, STAFF_ENROL, body.camera_id)
    if svc.enroller is None:
        raise Unavailable(NO_ENROLLER)
    if svc.frames.latest(body.camera_id) is None:
        raise NotFound(NO_FRAMES_RO)
    jpegs = await sample_frames(
        svc.frames, body.camera_id, body.seconds, SAMPLE_INTERVAL_S, capture_sleep
    )
    if not jpegs:
        raise NotFound(NO_FRAMES_RO)
    async with svc.sessions() as s:
        crops, thumbs = await _service(s, svc).capture_crops(jpegs)
    token = svc.captures.put(p.user_id, body.camera_id, loc, crops)
    return _capture_out(token, body.camera_id, len(jpegs), thumbs)


@router.post("/capture/frames")
async def capture_from_frames(
    svc: ServicesDep,
    access: EnrolAccess,
    frames: Annotated[list[UploadFile], File(description="JPEGs taken by the phone")],
) -> CaptureOut:
    """The same capture from JPEGs a phone took itself (one every ~1.5 s for ~20 s), so one
    phone does it all without streaming. Confirm with `/capture/{token}/confirm`."""
    if len(frames) > MAX_PHONE_FRAMES:
        raise Invalid(f"Prea multe imagini (cel mult {MAX_PHONE_FRAMES}).")
    if any((f.content_type or "") != "image/jpeg" for f in frames):
        raise Invalid("Imaginile trebuie să fie JPEG.")
    jpegs = []
    for f in frames:
        data = await f.read(MAX_PHONE_FRAME_BYTES + 1)
        if len(data) > MAX_PHONE_FRAME_BYTES:
            raise TooLarge("O imagine e prea mare (max 2 MB).")
        jpegs.append(data)
    if svc.enroller is None:
        raise Unavailable(NO_ENROLLER)
    async with svc.sessions() as s:
        crops, thumbs = await _service(s, svc).capture_crops(jpegs)
    token = svc.captures.put(access.principal.user_id, "", access.location_id, crops)
    return _capture_out(token, "", len(jpegs), thumbs)


def _capture_out(token: str, camera_id: str, frames: int, thumbs: list[bytes]) -> CaptureOut:
    return CaptureOut(
        token=token,
        camera_id=camera_id,
        frames=frames,
        candidates=[
            CaptureCandidate(
                index=i, thumbnail="data:image/jpeg;base64," + base64.b64encode(t).decode()
            )
            for i, t in enumerate(thumbs)
        ],
        expires_in_s=int(CAPTURE_TTL_S),
    )


@router.post("/capture/{token}/confirm")
async def confirm_capture(
    token: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{8,64}$")],
    body: CaptureConfirmIn,
    s: SessionDep,
    svc: ServicesDep,
    p: CurrentUser,
) -> EnrolOut:
    """Embed the kept candidates into a profile (a new one named `name`, or `profile_id`)
    and publish the profiles to the edges."""
    held = svc.captures.get(token, p.user_id)
    if held is None:
        raise NotFound(CAPTURE_GONE_RO)
    p.authorize(STAFF_ENROL, held.location_id)
    out = await _service(s, svc).enrol_crops(
        held.crops, body.keep, body.profile_id, body.name, body.description_ro
    )
    svc.captures.drop(token)
    await record(
        s,
        p,
        "staff.enrolled",
        location_id=held.location_id,
        target=Target("staff_profile", out.profile.id, out.profile.name),
        after={"camera_id": held.camera_id, "examples_added": out.examples_added},
        count=str(out.examples_added),
    )
    return out
