"""Which camera workers to start and stop when the device's retained config changes."""

import pytest
from aivee_edge.domain.fleet import FleetChanges, is_live_source, plan_fleet, wanted_cameras


@pytest.mark.parametrize(
    ("source", "live"),
    [
        ("rtsp://admin:pw@192.168.1.21:554/stream2", True),
        ("RTSP://192.168.1.21/stream2", True),
        ("rtsps://cam.local/stream", True),
        ("http://192.168.1.40:8080/video", True),
        ("https://cam.example/mjpeg", True),
        ("0", False),
        ("recordings/sala.mp4", False),
        ("mqtt-frames://cam-01", False),
        ("rtsp://", False),
        ("", False),
    ],
)
def test_live_sources_are_network_streams(source: str, live: bool) -> None:
    assert is_live_source(source) is live


def test_wanted_cameras_keeps_only_live_ones() -> None:
    cameras = [
        ("cam-01", "rtsp://a/stream2"),
        ("cam-02", "mqtt-frames://cam-02"),
        ("cam-03", "http://b:8080/video"),
        ("cam-04", "0"),
    ]
    assert wanted_cameras(cameras) == {
        "cam-01": "rtsp://a/stream2",
        "cam-03": "http://b:8080/video",
    }


def test_nothing_changes_when_config_matches() -> None:
    running = {"cam-01": "rtsp://a/1", "cam-02": "rtsp://b/1"}
    assert plan_fleet(running, dict(running)) == FleetChanges(start=[], stop=[])


def test_added_removed_and_changed_cameras() -> None:
    running = {"cam-01": "rtsp://a/1", "cam-02": "rtsp://b/1", "cam-03": "rtsp://c/1"}
    wanted = {"cam-01": "rtsp://a/1", "cam-03": "rtsp://c/2", "cam-04": "rtsp://d/1"}
    changes = plan_fleet(running, wanted)
    assert changes.stop == ["cam-02", "cam-03"]  # removed; source changed (stop, then start)
    assert changes.start == ["cam-03", "cam-04"]


def test_a_camera_that_failed_to_start_waits_for_a_new_source() -> None:
    wanted = {"cam-01": "rtsp://a/1", "cam-02": "rtsp://b/1"}
    failed = {"cam-02": "rtsp://b/1"}
    assert plan_fleet({}, wanted, failed).start == ["cam-01"]
    assert plan_fleet({}, {**wanted, "cam-02": "rtsp://b/2"}, failed).start == ["cam-01", "cam-02"]
