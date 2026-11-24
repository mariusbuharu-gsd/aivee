"""Camera-down reports from the live sources' health (V10)."""

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from aivee_edge.domain.camera_health import CameraHealth, SourceHealth
from aivee_edge.health import CameraHealthMonitor, LogHealth


class Live:
    def __init__(self) -> None:
        self.now = SourceHealth(True, 0.1, 15.0, 1280, 720)

    def health(self) -> SourceHealth:
        return self.now


class Clip:
    """A file or cloud source: no health()."""


class Sink:
    def __init__(self) -> None:
        self.calls: list[tuple[list[CameraHealth], list[CameraHealth]]] = []

    def report(self, every: Sequence[CameraHealth], changed: Sequence[CameraHealth]) -> None:
        self.calls.append((list(every), list(changed)))


def _monitor(sources: dict[str, object], *sinks: object, clock: list[float]) -> CameraHealthMonitor:
    return CameraHealthMonitor(
        sources,
        list(sinks),  # type: ignore[arg-type]
        clock=lambda: clock[0],
        wall=lambda: datetime(2026, 11, 23, 12, 0, tzinfo=UTC),
    )


def test_monitor_reports_live_cameras_only() -> None:
    sink, clock = Sink(), [0.0]
    monitor = _monitor({"cam-01": Live(), "clip": Clip()}, sink, clock=clock)
    monitor.tick()
    [(every, changed)] = sink.calls
    assert [h.camera_id for h in every] == ["cam-01"] and changed == []


def test_a_camera_down_is_logged_once_and_its_recovery_too(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = [0.0]
    one, two = Live(), Live()
    monitor = _monitor({"cam-01": one, "cam-02": two}, LogHealth(summary_every_s=1e9), clock=clock)
    with caplog.at_level("INFO"):
        monitor.tick()
        two.now = SourceHealth(False, 61.0, 0.0, 1280, 720)
        clock[0] = 61.0
        monitor.tick()
        monitor.tick()
        two.now = SourceHealth(True, 0.1, 15.0, 1280, 720)
        monitor.tick()
    downs = [r for r in caplog.records if "camera_down" in r.getMessage()]
    assert len(downs) == 1 and downs[0].levelname == "WARNING"
    assert "camera=cam-02" in downs[0].getMessage()
    assert "camera_up camera=cam-02" in caplog.text
    assert "camera=cam-01" not in caplog.text  # the healthy camera stays quiet


def test_log_health_prints_a_summary_every_interval(caplog: pytest.LogCaptureFixture) -> None:
    clock = [0.0]
    sink = LogHealth(summary_every_s=60, clock=lambda: clock[0])
    monitor = _monitor({"cam-01": Live()}, sink, clock=clock)
    with caplog.at_level("INFO"):
        monitor.tick()
        clock[0] = 30.0
        monitor.tick()
        clock[0] = 61.0
        monitor.tick()
    summaries = [
        r.getMessage() for r in caplog.records if r.getMessage().startswith("camera_health")
    ]
    assert summaries == [
        "camera_health cam-01=ok fps=15.0 size=1280x720 age_s=0.1",
        "camera_health cam-01=ok fps=15.0 size=1280x720 age_s=0.1",
    ]


def test_a_failing_sink_does_not_stop_the_others() -> None:
    class Boom:
        def report(self, *_a: object) -> None:
            raise RuntimeError("no broker")

    sink, clock = Sink(), [0.0]
    _monitor({"cam-01": Live()}, Boom(), sink, clock=clock).tick()
    assert len(sink.calls) == 1
