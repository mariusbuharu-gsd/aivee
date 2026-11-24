"""Camera-down reports from the live sources' health (V10)."""

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from aivee_contracts.events import CameraStreamHealth
from aivee_edge.domain.camera_health import CameraHealth, SourceHealth
from aivee_edge.health import CameraHealthMonitor, LogHealth, MqttHealth, tick_until


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


class Status:
    """Stands in for MqttEdgeClient.publish_camera_health."""

    def __init__(self) -> None:
        self.sent: list[list[CameraStreamHealth]] = []

    def publish_camera_health(self, health: list[CameraStreamHealth]) -> None:
        self.sent.append(health)


def test_mqtt_health_publishes_on_a_change_and_otherwise_once_a_minute() -> None:
    clock, status = [0.0], Status()
    one, two = Live(), Live()
    sink = MqttHealth(status, every_s=60, clock=lambda: clock[0])
    monitor = _monitor({"cam-01": one, "cam-02": two}, sink, clock=clock)
    monitor.tick()  # the first report goes out at once
    clock[0] = 30.0
    monitor.tick()  # nothing changed, under a minute: quiet
    assert len(status.sent) == 1
    two.now = SourceHealth(False, 61.0, 0.0, 1280, 720)
    clock[0] = 40.0
    monitor.tick()  # cam-02 went down: out now
    assert [(h.camera_id, h.state) for h in status.sent[-1]] == [
        ("cam-01", "ok"),
        ("cam-02", "down"),
    ]
    clock[0] = 90.0
    monitor.tick()
    assert len(status.sent) == 2  # 50 s since the last one
    clock[0] = 100.0
    monitor.tick()
    assert len(status.sent) == 3  # a minute since the last one


def test_mqtt_health_maps_the_edge_report_onto_the_contract() -> None:
    clock, status = [0.0], Status()
    never = Live()
    never.now = SourceHealth(False, None, 0.0)
    monitor = _monitor({"cam-01": Live(), "cam-02": never}, MqttHealth(status), clock=clock)
    monitor.tick()
    [[ok, waiting]] = status.sent
    assert ok == CameraStreamHealth(
        camera_id="cam-01",
        state="ok",
        last_frame_at=datetime(2026, 11, 23, 11, 59, 59, 900000, tzinfo=UTC),
        fps=15.0,
    )
    assert waiting.last_frame_at is None and waiting.state == "ok"


def test_tick_until_ticks_until_stop_or_done() -> None:
    import threading

    ticks: list[int] = []
    stop, done = threading.Event(), threading.Event()

    def tick() -> None:
        ticks.append(1)
        if len(ticks) == 3:
            done.set()

    thread = tick_until(tick, stop, done, tick_s=0.001)
    thread.join(timeout=2)
    assert not thread.is_alive() and len(ticks) == 3

    calls: list[int] = []
    finished = threading.Event()

    def boom_once() -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("bad sink")
        finished.set()

    tick_until(boom_once, threading.Event(), finished, tick_s=0.001).join(timeout=2)
    assert len(calls) == 2  # a failing tick is logged; the next one still runs
    stop.set()
    quiet: list[int] = []
    tick_until(lambda: quiet.append(1), stop, threading.Event(), tick_s=0.001).join(timeout=2)
    assert quiet == []


def test_cameras_can_be_added_to_and_removed_from_the_monitor() -> None:
    sink, clock = Sink(), [0.0]
    monitor = _monitor({}, sink, clock=clock)
    assert not monitor.watching
    monitor.tick()
    assert sink.calls == []
    monitor.add("cam-01", Live())
    monitor.add("clip", Clip())  # no health(): not watched
    monitor.add("cam-02", Live())
    monitor.tick()
    assert [h.camera_id for h in sink.calls[-1][0]] == ["cam-01", "cam-02"]
    monitor.remove("cam-01")
    monitor.remove("nope")
    monitor.tick()
    assert [h.camera_id for h in sink.calls[-1][0]] == ["cam-02"]
