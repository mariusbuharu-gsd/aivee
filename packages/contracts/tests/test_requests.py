"""Request/reply for one-off edge jobs (camera discovery, camera test) on `commands`/`replies`."""

from datetime import UTC, datetime

import pytest
from aivee_contracts.commands import (
    DiscoveredCamera,
    EdgeCommand,
    EdgeReply,
    EdgeRequest,
    parse_command,
)
from aivee_contracts.topics import Topics
from pydantic import ValidationError

AT = datetime(2026, 11, 6, tzinfo=UTC)


def test_replies_topic_is_per_device() -> None:
    t = Topics(site="demo", device="edge-01")
    assert t.replies == "aivee/demo/edge-01/replies"
    assert Topics.any_device("replies") == "aivee/+/+/replies"


def test_commands_topic_carries_staff_commands_and_requests() -> None:
    staff = EdgeCommand(
        command_id="c1",
        kind="confirm_staff",
        camera_id="cam-01",
        track_id=7,
        suggestion_id="s1",
        at=AT,
    )
    assert parse_command(staff.model_dump_json()) == staff
    test = EdgeRequest(
        request_id="r1", kind="test_camera", source="rtsp://u:p@192.168.1.21:554/stream2", at=AT
    )
    assert parse_command(test.model_dump_json().encode()) == test
    discover = EdgeRequest(request_id="r2", kind="discover_cameras", at=AT)
    assert parse_command(discover.model_dump_json()) == discover
    assert discover.source is None
    with pytest.raises(ValidationError):
        parse_command(b'{"kind": "format_disk", "request_id": "r3"}')
    with pytest.raises(ValidationError):
        parse_command(b"{bad")


def test_test_camera_request_needs_a_source() -> None:
    with pytest.raises(ValidationError):
        EdgeRequest(request_id="r1", kind="test_camera", at=AT)


def test_reply_round_trips_with_cameras_or_an_error() -> None:
    found = EdgeReply(
        request_id="r2",
        kind="discover_cameras",
        device="edge-01",
        ok=True,
        cameras=[
            DiscoveredCamera(
                ip="192.168.1.21",
                port=554,
                brand="tapo",
                model="C200",
                name="Tapo C200",
                onvif=True,
                rtsp_paths=["/stream2", "/stream1"],
            )
        ],
        at=AT,
    )
    assert EdgeReply.model_validate_json(found.model_dump_json()) == found
    failed = EdgeReply(
        request_id="r1", kind="test_camera", device="edge-01", ok=False, error="camera_auth", at=AT
    )
    assert failed.jpeg_b64 is None and failed.cameras == []
    with pytest.raises(ValidationError):
        DiscoveredCamera(ip="192.168.1.9", port=554, brand="acme", onvif=False)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        EdgeReply.model_validate({**failed.model_dump(), "error": "disk_full"})
