"""Web Push delivery.

`PushSender` is the port (tests use a fake); `WebPushSender` signs with VAPID and encrypts
with pywebpush. Push services answer 404/410 for a subscription the browser dropped, so
those rows are deleted; other failures are only counted.
"""

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

from aivee_api.push.settings import VapidSettings

GONE = frozenset({404, 410})
TTL_S = 15 * 60  # an alert older than 15 minutes is not worth waking a phone for

# What a push is about; the service worker rings again (renotify) only for "alert" and
# "realert". Mirrored by `PushKind` in apps/dashboard/src/push/payload.ts.
PushKind = Literal["alert", "ack", "arrived", "realert", "device", "test"]


@dataclass(frozen=True)
class Subscription:
    endpoint: str
    p256dh: str
    auth: str

    def info(self) -> dict[str, Any]:
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}}


@dataclass(frozen=True)
class PushMessage:
    """What the service worker shows. `url` opens on tap; `tag` replaces an older one;
    `kind` decides whether the replacement rings."""

    title: str
    body: str
    kind: PushKind
    url: str = "/alerte"
    tag: str = "aivee"

    def payload(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


@dataclass(frozen=True)
class PushReport:
    sent: int = 0
    removed: int = 0
    failed: int = 0


class PushSender(Protocol):
    async def send(self, sub: Subscription, payload: str) -> int:
        """Deliver `payload` to the push service; return its HTTP status (201 = queued)."""
        ...


class WebPushSender:
    def __init__(self, vapid: VapidSettings, timeout_s: float = 10) -> None:
        if not vapid.enabled:
            raise ValueError("VAPID keys are not configured")
        self._vapid = vapid
        self._timeout_s = timeout_s

    async def send(self, sub: Subscription, payload: str) -> int:
        from pywebpush import WebPushException, webpush_async  # type: ignore[import-untyped]

        try:
            await webpush_async(
                sub.info(),
                data=payload,
                vapid_private_key=self._vapid.private_key,
                # pywebpush adds `aud`/`exp` to the dict it gets, so pass a fresh one.
                vapid_claims={"sub": self._vapid.subject},
                ttl=TTL_S,
                timeout=self._timeout_s,
                headers={"Urgency": "high"},
            )
        except WebPushException as e:
            status = getattr(e.response, "status", None) or getattr(e.response, "status_code", 0)
            return int(status or 0)
        return 201
