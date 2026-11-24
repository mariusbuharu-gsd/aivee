from datetime import UTC, datetime, timedelta

from aivee_edge.domain.camera_health import (
    DOWN_AFTER_S,
    CameraHealth,
    CameraWatch,
    SourceHealth,
    stream_state,
)

T0 = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def _h(
    connected: bool = True, age: float | None = 0.1, fps: float = 15.0, reconnects: int = 1
) -> SourceHealth:
    return SourceHealth(connected, age, fps, 1280, 720, reconnects=reconnects)


def test_stream_state_ok_reconnecting_down() -> None:
    assert DOWN_AFTER_S == 60.0
    assert stream_state(_h(), running_s=100) == "ok"
    assert stream_state(_h(connected=False, age=5), running_s=100) == "reconnecting"
    assert stream_state(_h(connected=False, age=61), running_s=100) == "down"
    # connected but frozen (the camera sends nothing): down after 60 s too
    assert stream_state(_h(connected=True, age=61), running_s=100) == "down"


def test_a_camera_that_never_sent_a_frame_is_down_60s_after_start() -> None:
    never = _h(connected=False, age=None, fps=0)
    assert stream_state(never, running_s=30) == "reconnecting"
    assert stream_state(never, running_s=61) == "down"


def test_a_camera_still_opening_its_first_stream_is_not_reconnecting() -> None:
    opening = _h(connected=False, age=None, fps=0, reconnects=0)
    assert stream_state(opening, running_s=2) == "ok"
    assert stream_state(opening, running_s=61) == "down"  # an open that never ends


def test_watch_reports_state_changes_once() -> None:
    watch = CameraWatch()
    all_, changed = watch.observe(0.0, T0, {"cam-01": _h(), "cam-02": _h()})
    assert [h.state for h in all_] == ["ok", "ok"] and changed == []

    _, changed = watch.observe(10.0, T0, {"cam-01": _h(), "cam-02": _h(False, 3.0, 0)})
    assert [(h.camera_id, h.state) for h in changed] == [("cam-02", "reconnecting")]
    _, changed = watch.observe(20.0, T0, {"cam-01": _h(), "cam-02": _h(False, 13.0, 0)})
    assert changed == []  # still reconnecting: no repeat

    later = T0 + timedelta(seconds=70)
    all_, changed = watch.observe(70.0, later, {"cam-01": _h(), "cam-02": _h(False, 63.0, 0)})
    assert changed == [
        CameraHealth(
            camera_id="cam-02",
            state="down",
            last_frame_at=later - timedelta(seconds=63),
            last_frame_age_s=63.0,
            fps=0,
            width=1280,
            height=720,
        )
    ]
    assert [h.state for h in all_] == ["ok", "down"]

    _, changed = watch.observe(80.0, later, {"cam-01": _h(), "cam-02": _h()})
    assert [(h.camera_id, h.state) for h in changed] == [("cam-02", "ok")]


def test_watch_reports_a_camera_that_is_down_from_the_start() -> None:
    watch = CameraWatch()
    never = _h(connected=False, age=None, fps=0)
    _, changed = watch.observe(0.0, T0, {"cam-01": never})
    assert [h.state for h in changed] == ["reconnecting"]
    all_, changed = watch.observe(61.0, T0, {"cam-01": never})
    assert [h.state for h in changed] == ["down"]
    assert all_[0].last_frame_at is None
