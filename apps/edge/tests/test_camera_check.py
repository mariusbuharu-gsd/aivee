"""tools/camera_check.py: open each camera for a few seconds and say what it delivers."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from aivee_edge.domain.camera_health import SourceHealth

TOOL = Path(__file__).resolve().parents[3] / "tools" / "camera_check.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("camera_check", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["camera_check"] = module
    spec.loader.exec_module(module)
    return module


camera_check = _load()


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += s


class FakeStream:
    """First frame after `first_at` seconds, then 15 fps of 1280x720 h264; `dead` never opens."""

    def __init__(self, clock: Clock, first_at: float = 0.4, dead: bool = False) -> None:
        self.clock, self.first_at, self.dead = clock, first_at, dead
        self.started = self.closed = False

    def start(self) -> None:
        self.started = True

    def health(self) -> SourceHealth:
        if self.dead or self.clock.now < self.first_at:
            return SourceHealth(False, None, 0.0)
        # A 60-frame burst right after the first frame (the probe backlog), then 15 fps.
        frames = 60 + int((self.clock.now - self.first_at) * 15)
        return SourceHealth(True, 0.0, 33.0, 1280, 720, frames=frames, codec="h264")

    def ended(self) -> bool:
        return self.closed or (self.dead and self.clock.now > 1.0)

    def close(self) -> None:
        self.closed = True


def test_a_working_camera_reports_resolution_fps_latency_and_codec() -> None:
    clock = Clock()
    stream = FakeStream(clock)
    result = camera_check.check(
        "cam-01", "rtsp://admin:s3cr3t@10.0.0.21:554/stream2", 8.0,
        open_stream=lambda _url: stream, clock=clock, sleep=clock.sleep,
    )  # fmt: skip
    assert result.ok
    assert (result.width, result.height, result.codec) == (1280, 720, "h264")
    assert result.fps == pytest.approx(15.0, abs=0.6)  # the start-up burst is left out
    assert result.first_frame_s == pytest.approx(0.4, abs=0.11)
    assert stream.started and stream.closed
    line = camera_check.describe(result)
    assert line.startswith("OK")
    assert "rtsp://admin:***@10.0.0.21:554/stream2" in line and "s3cr3t" not in line
    assert "1280x720" in line and " fps " in line and "codec h264" in line


def test_a_dead_camera_fails_with_a_redacted_url() -> None:
    clock = Clock()
    result = camera_check.check(
        "cam-02", "rtsp://admin:s3cr3t@10.0.0.22:554/stream2", 5.0,
        open_stream=lambda _url: FakeStream(clock, dead=True), clock=clock, sleep=clock.sleep,
    )  # fmt: skip
    assert not result.ok
    line = camera_check.describe(result)
    assert line.startswith("FAIL") and "s3cr3t" not in line and "no frame" in line


def test_a_main_stream_gets_a_substream_hint() -> None:
    result = camera_check.Result("cam-01", "rtsp://h/stream1", True, 2560, 1440, 15.0, 0.5, "h264")
    assert "stream2" in camera_check.describe(result)


def test_targets_come_from_arguments_or_cameras(monkeypatch: pytest.MonkeyPatch) -> None:
    assert camera_check.targets(["rtsp://a/1", "cam-02=rtsp://b/2"], cameras="") == [
        ("camera-1", "rtsp://a/1"),
        ("cam-02", "rtsp://b/2"),
    ]
    assert camera_check.targets([], cameras="cam-01=rtsp://a/1;cam-02=rtsp://b/2") == [
        ("cam-01", "rtsp://a/1"),
        ("cam-02", "rtsp://b/2"),
    ]
    assert camera_check.targets([], cameras="") == []


def test_exit_code_is_non_zero_when_a_camera_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = Clock()
    streams = {"rtsp://ok/2": FakeStream(clock), "rtsp://dead/2": FakeStream(clock, dead=True)}
    monkeypatch.setattr(camera_check, "open_stream", lambda url: streams[url])
    monkeypatch.setattr(camera_check, "_clock", clock)
    monkeypatch.setattr(camera_check, "_sleep", clock.sleep)
    assert camera_check.main(["--seconds", "5", "rtsp://ok/2"]) == 0
    assert camera_check.main(["--seconds", "5", "rtsp://ok/2", "rtsp://dead/2"]) == 1
    out = capsys.readouterr().out
    assert "OK" in out and "FAIL" in out


def test_no_camera_given_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAMERAS", raising=False)
    assert camera_check.main(["--env-file", "/nonexistent/.env"]) == 2


def test_a_short_run_says_its_fps_is_not_settled() -> None:
    clock = Clock()
    result = camera_check.check(
        "cam-01", "rtsp://h/stream2", 2.0,
        open_stream=lambda _url: FakeStream(clock), clock=clock, sleep=clock.sleep,
    )  # fmt: skip
    assert result.ok and not result.fps_settled
    assert "--seconds 8" in camera_check.describe(result)
