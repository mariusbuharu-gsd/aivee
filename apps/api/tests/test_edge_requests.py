"""Request/reply over MQTT, without a broker: the API asks a device and waits for its answer."""

import asyncio
import json
from datetime import UTC, datetime

import pytest
from aivee_api.edge.publisher import MqttEdgeLink, PublisherUnavailable, RecordingPublisher
from aivee_api.edge.requests import EdgeRequests, EdgeTimeout, EdgeUnreachable
from aivee_api.metrics.cache import MetricsCache
from aivee_api.settings import ApiSettings
from aivee_contracts.commands import EdgeReply, EdgeRequest
from aivee_contracts.topics import Topics

AT = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def _requests(publisher: object) -> EdgeRequests:
    ids = iter(["r1", "r2", "r3"])
    return EdgeRequests(publisher, "demo", new_id=lambda: next(ids), clock=lambda: AT)  # type: ignore[arg-type]


def _reply(request_id: str = "r1", device: str = "edge-01") -> EdgeReply:
    return EdgeReply(request_id=request_id, kind="discover_cameras", device=device, ok=True, at=AT)


async def test_ask_publishes_the_request_and_returns_the_reply() -> None:
    publisher = RecordingPublisher()
    requests = _requests(publisher)
    task = asyncio.create_task(requests.ask("edge-01", "discover_cameras", timeout_s=5))
    await asyncio.sleep(0)
    [msg] = publisher.messages
    assert (msg.topic, msg.qos, msg.retain) == (Topics("demo", "edge-01").commands, 1, False)
    assert EdgeRequest.model_validate_json(msg.payload) == EdgeRequest(
        request_id="r1", kind="discover_cameras", at=AT
    )
    assert requests.resolve("edge-01", _reply()) is True
    assert (await task).request_id == "r1"
    assert requests.pending == 0


async def test_test_camera_carries_the_source() -> None:
    publisher = RecordingPublisher()
    requests = _requests(publisher)
    task = asyncio.create_task(
        requests.ask("edge-01", "test_camera", source="rtsp://u:p@h/s", timeout_s=5)
    )
    await asyncio.sleep(0)
    assert json.loads(publisher.messages[0].payload)["source"] == "rtsp://u:p@h/s"
    requests.resolve("edge-01", _reply())
    await task


async def test_a_reply_from_another_device_or_an_unknown_request_is_ignored() -> None:
    requests = _requests(RecordingPublisher())
    task = asyncio.create_task(requests.ask("edge-01", "discover_cameras", timeout_s=0.1))
    await asyncio.sleep(0)
    assert requests.resolve("edge-99", _reply()) is False  # the broker said edge-99 sent it
    assert requests.resolve("edge-01", _reply("nope")) is False
    with pytest.raises(EdgeTimeout):
        await task
    assert requests.pending == 0
    assert requests.resolve("edge-01", _reply()) is False  # too late


async def test_no_broker_is_unreachable() -> None:
    class Down:
        async def publish(self, *_a: object, **_k: object) -> None:
            raise PublisherUnavailable("not connected")

    with pytest.raises(EdgeUnreachable):
        await _requests(Down()).ask("edge-01", "discover_cameras", timeout_s=1)


async def test_the_link_hands_replies_to_the_waiting_request() -> None:
    link = MqttEdgeLink(ApiSettings(site="demo"), MetricsCache())
    requests = _requests(link)
    link.replies = requests
    resolved: list[tuple[str, str]] = []
    requests.resolve = lambda device, reply: bool(  # type: ignore[method-assign]
        resolved.append((device, reply.request_id))
    )
    topic = Topics("demo", "edge-01").replies
    link._on_message(topic, _reply().model_dump_json().encode())
    link._on_message(topic, b"{not json")
    assert resolved == [("edge-01", "r1")]
