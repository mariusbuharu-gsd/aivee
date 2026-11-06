from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.audit.record import record
from aivee_api.audit.repository import Target
from aivee_api.auth.deps import Access, CurrentUser, require
from aivee_api.auth.permissions import STAFF_ENROL, STAFF_REVIEW
from aivee_api.auth.principal import Principal
from aivee_api.auth.scope import authorize_at, suggestion_location
from aivee_api.db.repositories import CameraRepository, SuggestionRepository
from aivee_api.deps import Services, ServicesDep, SessionDep
from aivee_api.errors import Invalid
from aivee_api.events.schemas import SuggestionOut
from aivee_api.staff.enrol import Upload
from aivee_api.staff.schemas import DecisionOut, EnrolOut, ProfileOut
from aivee_api.staff.service import StaffService

router = APIRouter(prefix="/api/staff", tags=["staff"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


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
