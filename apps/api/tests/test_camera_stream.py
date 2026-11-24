"""A camera's stream state from its device's state and last reported camera health."""

from datetime import UTC, datetime

from aivee_api.cameras.service import camera_stream

HEALTH = [
    {"camera_id": "cam1", "state": "reconnecting", "last_frame_at": "2026-11-23T12:00:00Z"},
    {"camera_id": "cam2", "state": "bogus", "last_frame_at": "not a time"},
]


def test_an_online_device_speaks_for_each_of_its_cameras() -> None:
    stream = camera_stream("cam1", "online", HEALTH)
    assert stream.state == "reconnecting" and stream.online is True
    assert stream.last_frame_at == datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def test_unknown_health_is_none_and_the_camera_follows_its_device() -> None:
    for camera_id, health in [("cam3", HEALTH), ("cam1", []), ("cam1", None)]:
        stream = camera_stream(camera_id, "online", health)
        assert (stream.state, stream.last_frame_at, stream.online) == (None, None, True)


def test_a_bad_entry_counts_as_unknown() -> None:
    stream = camera_stream("cam2", "online", HEALTH)
    assert (stream.state, stream.last_frame_at, stream.online) == (None, None, True)


def test_a_down_camera_is_not_online() -> None:
    stream = camera_stream("cam1", "online", [{"camera_id": "cam1", "state": "down"}])
    assert (stream.state, stream.online) == ("down", False)


def test_an_offline_device_takes_every_camera_down() -> None:
    stream = camera_stream("cam1", "offline", HEALTH)
    assert (stream.state, stream.online) == ("down", False)
    assert stream.last_frame_at == datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def test_a_camera_without_a_device_is_unknown() -> None:
    stream = camera_stream("cam1", None, None)
    assert (stream.state, stream.last_frame_at, stream.online) == (None, None, False)
