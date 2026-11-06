"""The real WebPushSender against a local stand-in for a push service.

The "browser" is a generated P-256 key pair plus auth secret, so the test can decrypt what
pywebpush sent and check the VAPID header, exactly as FCM or Mozilla's service would receive it.
"""

import base64
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import http_ece
import pytest
from aiohttp import web
from aivee_api.push.sender import PushMessage, Subscription, WebPushSender
from aivee_api.push.settings import VapidSettings
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _vapid() -> VapidSettings:
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    private = key.private_numbers().private_value.to_bytes(32, "big")
    return VapidSettings(
        public_key=_b64(public), private_key=_b64(private), subject="mailto:t@example.com"
    )


@dataclass
class PushService:
    base: str
    status: int = 201
    received: list[tuple[dict[str, str], bytes]] = field(default_factory=list)


@pytest.fixture
async def push_service(unused_tcp_port: int) -> AsyncIterator[PushService]:
    svc = PushService(base=f"http://127.0.0.1:{unused_tcp_port}")

    async def receive(request: web.Request) -> web.Response:
        svc.received.append(
            ({k.lower(): v for k, v in request.headers.items()}, await request.read())
        )
        return web.Response(status=svc.status)

    app = web.Application()
    app.router.add_post("/push/{id}", receive)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
    yield svc
    await runner.cleanup()


def _browser(base: str) -> tuple[Subscription, ec.EllipticCurvePrivateKey, bytes]:
    key = ec.generate_private_key(ec.SECP256R1())
    auth = os.urandom(16)
    p256dh = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return Subscription(f"{base}/push/abc", _b64(p256dh), _b64(auth)), key, auth


async def test_sends_an_encrypted_vapid_signed_message(push_service: PushService) -> None:
    vapid = _vapid()
    sub, key, auth = _browser(push_service.base)
    message = PushMessage(
        title="Alertă AiVee · Masa 1", body="Masa 1 așteaptă de 1 min", kind="alert", tag="e1"
    )

    assert await WebPushSender(vapid).send(sub, message.payload()) == 201

    ((headers, body),) = push_service.received
    assert headers["content-encoding"] == "aes128gcm"
    assert int(headers["ttl"]) > 0 and headers["urgency"] == "high"
    assert headers["authorization"].startswith("vapid t=")
    assert f"k={vapid.public_key}" in headers["authorization"]
    plain = http_ece.decrypt(body, private_key=key, auth_secret=auth, version="aes128gcm")
    assert json.loads(plain) == {
        "title": "Alertă AiVee · Masa 1",
        "body": "Masa 1 așteaptă de 1 min",
        "kind": "alert",
        "url": "/alerte",
        "tag": "e1",
    }


@pytest.mark.parametrize("status", [404, 410, 500])
async def test_returns_the_push_service_status_on_failure(
    push_service: PushService, status: int
) -> None:
    push_service.status = status
    sub, _, _ = _browser(push_service.base)
    assert await WebPushSender(_vapid()).send(sub, "{}") == status
