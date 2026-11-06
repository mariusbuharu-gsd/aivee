"""`/api/push/*`: the VAPID public key, (un)subscribe, and a test push for the demo."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, field_validator

from aivee_api.auth.deps import CurrentUser
from aivee_api.deps import ServicesDep, SessionDep
from aivee_api.errors import Unavailable
from aivee_api.push.repository import PushSubscriptionRepository
from aivee_api.push.sender import PushMessage, PushReport, PushSender, Subscription, WebPushSender
from aivee_api.push.service import push_to_user
from aivee_api.push.settings import VapidSettings

router = APIRouter(prefix="/api/push", tags=["push"])

NOT_CONFIGURED = "Notificările push nu sunt configurate pe server (lipsesc cheile VAPID)."


def get_vapid(request: Request) -> VapidSettings:
    """`app.state.vapid` when set (tests), else from env."""
    vapid: VapidSettings | None = getattr(request.app.state, "vapid", None)
    if vapid is None:
        vapid = VapidSettings()
        request.app.state.vapid = vapid
    return vapid


VapidDep = Annotated[VapidSettings, Depends(get_vapid)]


def get_sender(request: Request, vapid: VapidDep) -> PushSender:
    """`app.state.push_sender` when set (tests), else a real VAPID sender."""
    sender: PushSender | None = getattr(request.app.state, "push_sender", None)
    if sender is not None:
        return sender
    if not vapid.enabled:
        raise Unavailable(NOT_CONFIGURED)
    return WebPushSender(vapid)


class PublicKeyOut(BaseModel):
    public_key: str


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class SubscriptionIn(BaseModel):
    """The browser's `PushSubscription.toJSON()`; `expirationTime` is accepted and ignored."""

    endpoint: str = Field(max_length=1000)
    keys: SubscriptionKeys
    expirationTime: int | None = None  # the browser's field name

    @field_validator("endpoint")
    @classmethod
    def _https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("endpoint must be an https URL")
        return v


class UnsubscribeIn(BaseModel):
    endpoint: str = Field(max_length=1000)


@router.get("/public-key")
async def public_key(vapid: VapidDep) -> PublicKeyOut:
    if not vapid.enabled:
        raise Unavailable(NOT_CONFIGURED)
    return PublicKeyOut(public_key=vapid.public_key)


@router.post("/subscribe", status_code=201)
async def subscribe(
    body: SubscriptionIn, request: Request, p: CurrentUser, s: SessionDep
) -> dict[str, bool]:
    """The subscription belongs to the logged-in user: alerts reach it only for their
    locations."""
    sub = Subscription(body.endpoint, body.keys.p256dh, body.keys.auth)
    await PushSubscriptionRepository(s).upsert(
        sub, request.headers.get("user-agent", ""), user_id=p.user_id
    )
    await s.commit()
    return {"subscribed": True}


@router.delete("/subscribe", status_code=204)
async def unsubscribe(body: UnsubscribeIn, p: CurrentUser, s: SessionDep) -> Response:
    """Idempotent: unknown endpoints are fine (the browser may already have dropped it).
    Only the caller's own subscription is removed."""
    await PushSubscriptionRepository(s).delete(body.endpoint, user_id=p.user_id)
    await s.commit()
    return Response(status_code=204)


@router.post("/test")
async def send_test(
    p: CurrentUser, svc: ServicesDep, sender: Annotated[PushSender, Depends(get_sender)]
) -> PushReport:
    """Send a test notification to the caller's own subscribed devices (setup check)."""
    message = PushMessage(
        title="AiVee",
        body="Test reușit: aici primești alertele AiVee.",
        kind="test",
        url="/alerte",
        tag="aivee-test",
    )
    return await push_to_user(svc.sessions, sender, message, p.user_id)
