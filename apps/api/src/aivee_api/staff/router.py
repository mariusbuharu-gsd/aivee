from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

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


@router.get("/suggestions")
async def list_suggestions(s: SessionDep, svc: ServicesDep) -> list[SuggestionOut]:
    return await _service(s, svc).pending_suggestions()


@router.post("/suggestions/{suggestion_id}/confirm")
async def confirm_suggestion(suggestion_id: str, s: SessionDep, svc: ServicesDep) -> DecisionOut:
    st = svc.settings
    return await _service(s, svc).decide(
        suggestion_id, True, st.default_profile_id, st.default_profile_name
    )


@router.post("/suggestions/{suggestion_id}/reject")
async def reject_suggestion(suggestion_id: str, s: SessionDep, svc: ServicesDep) -> DecisionOut:
    st = svc.settings
    return await _service(s, svc).decide(
        suggestion_id, False, st.default_profile_id, st.default_profile_name
    )


@router.get("/profiles")
async def list_profiles(s: SessionDep, svc: ServicesDep) -> list[ProfileOut]:
    return await _service(s, svc).profiles()


@router.post("/photos")
async def upload_photos(
    s: SessionDep,
    svc: ServicesDep,
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
    return await _service(s, svc).enrol(
        uploads,
        profile_id or st.default_profile_id,
        name or st.default_profile_name,
        description_ro,
    )
