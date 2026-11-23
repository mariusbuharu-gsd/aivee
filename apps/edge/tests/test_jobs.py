"""One-off jobs the dashboard asks the edge for: each request gets exactly one reply."""

import base64
import threading
from datetime import UTC, datetime

import pytest
from aivee_contracts.commands import DiscoveredCamera, EdgeReply, EdgeRequest
from aivee_edge.adapters.camera_still import CameraTestError, Still
from aivee_edge.jobs import EdgeJobs

AT = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
TAPO = DiscoveredCamera(ip="192.168.1.21", brand="tapo", rtsp_paths=["/stream2", "/stream1"])


def _jobs(test: object = None, discover: object = None) -> tuple[EdgeJobs, list[EdgeReply]]:
    replies: list[EdgeReply] = []

    def default_test(_source: str) -> Still:
        return Still(jpeg=b"\xff\xd8jpeg", width=640, height=360, at=AT)

    jobs = EdgeJobs(
        "edge-01",
        replies.append,
        discover=discover or (lambda: [TAPO]),  # type: ignore[arg-type]
        test=test or default_test,  # type: ignore[arg-type]
        clock=lambda: AT,
    )
    return jobs, replies


def test_discovery_replies_with_the_cameras() -> None:
    jobs, _ = _jobs()
    reply = jobs.handle(EdgeRequest(request_id="r1", kind="discover_cameras", at=AT))
    assert reply.model_dump(exclude={"cameras"}) == {
        "request_id": "r1",
        "kind": "discover_cameras",
        "device": "edge-01",
        "ok": True,
        "error": None,
        "jpeg_b64": None,
        "width": None,
        "height": None,
        "frame_at": None,
        "at": AT,
    }
    assert reply.cameras == [TAPO]


def test_a_camera_test_replies_with_the_jpeg(caplog: pytest.LogCaptureFixture) -> None:
    jobs, _ = _jobs()
    source = "rtsp://admin:s3cr3t@192.168.1.21:554/stream2"
    with caplog.at_level("INFO"):
        reply = jobs.handle(EdgeRequest(request_id="r2", kind="test_camera", source=source, at=AT))
    assert reply.ok and reply.error is None
    assert base64.b64decode(reply.jpeg_b64 or "") == b"\xff\xd8jpeg"
    assert (reply.width, reply.height, reply.frame_at) == (640, 360, AT)
    assert "s3cr3t" not in caplog.text and "camera_test request_id=r2 ok" in caplog.text


def test_a_failed_camera_test_replies_with_its_code(caplog: pytest.LogCaptureFixture) -> None:
    def refuse(_source: str) -> Still:
        raise CameraTestError("camera_auth")

    jobs, _ = _jobs(test=refuse)
    request = EdgeRequest(
        request_id="r3", kind="test_camera", source="rtsp://admin:s3cr3t@h/s", at=AT
    )
    with caplog.at_level("INFO"):
        reply = jobs.handle(request)
    assert (reply.ok, reply.error, reply.jpeg_b64) == (False, "camera_auth", None)
    assert "s3cr3t" not in caplog.text


def test_a_job_that_breaks_replies_failed_without_leaking_the_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def boom(source: str) -> Still:
        raise RuntimeError(f"cannot open {source}")

    jobs, _ = _jobs(test=boom)
    request = EdgeRequest(
        request_id="r4", kind="test_camera", source="rtsp://admin:s3cr3t@h/s", at=AT
    )
    with caplog.at_level("INFO"):
        reply = jobs.handle(request)
    assert (reply.ok, reply.error) == (False, "failed")
    assert "s3cr3t" not in caplog.text and "rtsp://admin:***@h/s" in caplog.text


def test_submit_runs_off_the_network_thread_and_publishes_one_reply() -> None:
    gate = threading.Event()
    seen: list[str] = []

    def slow_discover() -> list[DiscoveredCamera]:
        seen.append(threading.current_thread().name)
        gate.wait(5)
        return []

    jobs, replies = _jobs(discover=slow_discover)
    jobs.submit(EdgeRequest(request_id="r5", kind="discover_cameras", at=AT))  # returns at once
    assert replies == []
    gate.set()
    jobs.close(wait=True)
    assert [r.request_id for r in replies] == ["r5"]
    assert seen and seen[0] != threading.current_thread().name


def test_a_publish_failure_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    def broken(_reply: EdgeReply) -> None:
        raise OSError("broker gone")

    jobs = EdgeJobs("edge-01", broken, discover=lambda: [], test=lambda _s: None, clock=lambda: AT)  # type: ignore[arg-type,return-value]
    jobs.submit(EdgeRequest(request_id="r6", kind="discover_cameras", at=AT))
    jobs.close(wait=True)
    assert "reply_failed request_id=r6" in caplog.text
