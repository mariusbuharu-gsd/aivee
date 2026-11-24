"""Request/reply with an edge device over MQTT, for one-off jobs (camera discovery, camera test).

`EdgeRequests.ask()` publishes an `EdgeRequest` on the device's `commands` topic (QoS 1, not
retained) and waits for the `EdgeReply` with the same `request_id` on its `replies` topic,
which `MqttEdgeLink` hands over (`resolve`). The device in the reply's topic (enforced by the
broker ACL) must be the one asked, so a device cannot answer for another. Single event loop.
"""

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from aivee_contracts.commands import EdgeReply, EdgeRequest, RequestKind
from aivee_contracts.topics import Topics

from aivee_api.edge.publisher import EdgePublisher, PublisherUnavailable

QOS_REQUEST = 1


class EdgeTimeout(Exception):
    """The device did not answer in time."""


class EdgeUnreachable(Exception):
    """The broker is not connected: the request could not be sent."""


class EdgeAsk(Protocol):
    async def ask(
        self, device: str, kind: RequestKind, *, source: str | None = None, timeout_s: float
    ) -> EdgeReply: ...


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class EdgeRequests:
    def __init__(
        self,
        publisher: EdgePublisher,
        site: str,
        *,
        new_id: Callable[[], str] = _new_id,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._publisher = publisher
        self._site = site
        self._new_id = new_id
        self._clock = clock
        self._pending: dict[str, tuple[str, asyncio.Future[EdgeReply]]] = {}

    @property
    def pending(self) -> int:
        return len(self._pending)

    async def ask(
        self, device: str, kind: RequestKind, *, source: str | None = None, timeout_s: float
    ) -> EdgeReply:
        """Send one request to `device` and return its reply. Raises `EdgeTimeout` after
        `timeout_s`, `EdgeUnreachable` when the broker is not connected."""
        request = EdgeRequest(request_id=self._new_id(), kind=kind, at=self._clock(), source=source)
        future: asyncio.Future[EdgeReply] = asyncio.get_running_loop().create_future()
        self._pending[request.request_id] = (device, future)
        try:
            topic = Topics(site=self._site, device=device).commands
            try:
                await self._publisher.publish(
                    topic, request.model_dump_json().encode(), qos=QOS_REQUEST, retain=False
                )
            except PublisherUnavailable as e:
                raise EdgeUnreachable(str(e)) from e
            try:
                return await asyncio.wait_for(future, timeout_s)
            except TimeoutError:
                raise EdgeTimeout(f"{device} did not answer {kind} in {timeout_s:.0f}s") from None
        finally:
            self._pending.pop(request.request_id, None)

    def resolve(self, device: str, reply: EdgeReply) -> bool:
        """Hand a reply that arrived on `device`'s replies topic to its waiting request.
        False when nobody waits for it (late, unknown, or from another device)."""
        waiting = self._pending.get(reply.request_id)
        if waiting is None:
            return False
        expected, future = waiting
        if expected != device or future.done():
            return False
        future.set_result(reply)
        return True
