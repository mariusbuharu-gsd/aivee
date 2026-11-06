"""`GET /api/capabilities`: which optional features this server runs, so the dashboard can
hide what would only answer 503 (the cloud deploy has no clip runner, for example)."""

from fastapi import APIRouter
from pydantic import BaseModel

from aivee_api.auth.deps import CurrentUser
from aivee_api.deps import Services, ServicesDep
from aivee_api.videos.kind import is_upload_device

router = APIRouter(prefix="/api", tags=["capabilities"])


class Capabilities(BaseModel):
    videos: bool
    """`POST /api/videos` can analyse a clip here."""
    enrol: bool
    """Staff profiles can be built here (photo upload, live capture)."""


def videos_available(svc: Services) -> bool:
    """The same checks `POST /api/videos` answers 503 on."""
    s = svc.settings
    return (
        svc.videos is not None
        and bool(s.mqtt_upload_password)
        and is_upload_device(s.mqtt_upload_user)
    )


def capabilities(svc: Services) -> Capabilities:
    return Capabilities(videos=videos_available(svc), enrol=svc.enroller is not None)


@router.get("/capabilities")
async def get_capabilities(svc: ServicesDep, p: CurrentUser) -> Capabilities:
    """Any signed-in user; the per-feature permissions still apply on each route."""
    return capabilities(svc)
