import itertools
import os
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import cv2
import numpy as np
import pytest
from aivee_edge.adapters.capture import Cv2Source, FileSource, next_due, rotate


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    """30 frames at 30 fps (1 s); frame i has brightness 8*i so frames are tellable apart."""
    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 48))
    assert writer.isOpened()
    for i in range(30):
        writer.write(np.full((48, 64, 3), 8 * i, dtype=np.uint8))
    writer.release()
    return path


def drain(source: FileSource, limit: int = 1000) -> list[tuple[float, np.ndarray]]:
    out = []
    while len(out) < limit and (item := source.read()) is not None:
        out.append(item)
    return out


def test_file_source_yields_frames(clip: Path) -> None:
    frames = drain(FileSource(clip, target_fps=30))
    assert len(frames) == 30
    ts, image = frames[0]
    assert ts == 0.0
    assert image.shape == (48, 64, 3)


def test_file_source_drops_to_target_fps_with_video_timestamps(clip: Path) -> None:
    frames = drain(FileSource(clip, target_fps=10))
    assert len(frames) == 10
    stamps = [ts for ts, _ in frames]
    assert stamps == pytest.approx([i / 10 for i in range(10)], abs=1e-6)
    # every 3rd frame kept: brightness 0, 24, 48, ...
    assert [round(img.mean() / 24) for _, img in frames[:4]] == [0, 1, 2, 3]


def test_file_source_loop_keeps_timestamps_monotonic(clip: Path) -> None:
    frames = drain(FileSource(clip, target_fps=10, loop=True), limit=25)
    stamps = [ts for ts, _ in frames]
    assert len(stamps) == 25
    assert all(b > a for a, b in itertools.pairwise(stamps))
    assert stamps[10] == pytest.approx(1.0)


def test_file_source_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        FileSource(tmp_path / "nope.avi")


def test_cv2_source_drops_frames_by_wall_clock(clip: Path) -> None:
    now = [0.0]

    def clock() -> float:
        now[0] += 0.04  # each read advances 40 ms (25 fps camera)
        return now[0]

    source = Cv2Source(str(clip), target_fps=5, clock=clock, max_reconnects=0)
    first = source.read()
    second = source.read()
    source.close()
    assert first is not None and second is not None
    assert second[0] - first[0] >= 0.2 - 1e-9


def _marked() -> np.ndarray:
    """2x3 image whose top-left pixel is white, so every rotation is tellable apart."""
    image = np.zeros((2, 3, 3), dtype=np.uint8)
    image[0, 0] = 255
    return image


@pytest.mark.parametrize(
    ("degrees", "shape", "white"),
    [
        (0, (2, 3, 3), (0, 0)),
        (90, (3, 2, 3), (0, 1)),
        (180, (2, 3, 3), (1, 2)),
        (270, (3, 2, 3), (2, 0)),
    ],
)
def test_rotate_turns_the_image_clockwise(
    degrees: int, shape: tuple[int, ...], white: tuple[int, int]
) -> None:
    out = rotate(_marked(), degrees)
    assert out.shape == shape
    assert tuple(int(v) for v in np.argwhere(out[:, :, 0] == 255)[0]) == white


def test_rotate_rejects_other_angles() -> None:
    with pytest.raises(ValueError):
        rotate(_marked(), 45)


def test_file_source_applies_rotation_before_returning_frames(clip: Path) -> None:
    [(_, image)] = drain(FileSource(clip, target_fps=30, rotate=90), limit=1)
    assert image.shape == (64, 48, 3)


def test_cv2_source_applies_rotation(clip: Path) -> None:
    source = Cv2Source(str(clip), target_fps=0, max_reconnects=0, rotate=270)
    item = source.read()
    assert item is not None and item[1].shape == (64, 48, 3)
    source.close()


def test_cv2_source_gives_up_after_max_reconnects(tmp_path: Path) -> None:
    sleeps: list[float] = []
    source = Cv2Source(
        str(tmp_path / "missing.avi"), target_fps=5, max_reconnects=3, sleep=sleeps.append
    )
    assert source.read() is None
    assert source.ended()
    assert sleeps == [0.5, 1.0, 2.0]


class _FakeCapture:
    calls: ClassVar[list[tuple[object, ...]]] = []

    def __init__(self, *args: object) -> None:
        _FakeCapture.calls.append(args)

    def set(self, *_a: object) -> bool:
        return True

    def isOpened(self) -> bool:
        return True

    def release(self) -> None:
        pass


@pytest.mark.parametrize(
    "url", ["rtsp://mediamtx:8554/cam-01", "rtsps://h/cam", "http://192.168.1.30:8080/video"]
)
def test_network_sources_decode_on_one_thread_with_timeouts(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    # Frame threading holds about one frame per decoder thread: at 5 fps on 12 cores that is
    # ~2.4 s of lag behind the camera. One thread keeps the reader live. The timeouts stop a
    # dead camera from blocking the grabber forever.
    _FakeCapture.calls = []
    monkeypatch.setattr(cv2, "VideoCapture", _FakeCapture)
    assert Cv2Source(url, target_fps=5, timeout_s=4)._open() is not None
    [(opened, backend, params)] = _FakeCapture.calls
    assert (opened, backend) == (url, cv2.CAP_FFMPEG)
    assert isinstance(params, list)
    assert dict(zip(params[::2], params[1::2], strict=True)) == {
        cv2.CAP_PROP_N_THREADS: 1,
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC: 4000,
        cv2.CAP_PROP_READ_TIMEOUT_MSEC: 4000,
    }


def test_network_sources_force_rtsp_over_tcp(monkeypatch: pytest.MonkeyPatch) -> None:
    # UDP over Wi-Fi loses packets and smears the picture; TCP is what NVRs use.
    monkeypatch.delenv("OPENCV_FFMPEG_CAPTURE_OPTIONS", raising=False)
    monkeypatch.setattr(cv2, "VideoCapture", _FakeCapture)
    Cv2Source("rtsp://cam/stream2", target_fps=5, timeout_s=4)._open()
    options = os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"].split("|")
    assert "rtsp_transport;tcp" in options
    assert "timeout;4000000" in options  # FFmpeg socket I/O timeout, microseconds


def test_ffmpeg_options_set_by_the_operator_are_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;udp")
    monkeypatch.setattr(cv2, "VideoCapture", _FakeCapture)
    Cv2Source("rtsp://cam/stream2", target_fps=5)._open()
    assert os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] == "rtsp_transport;udp"


def test_webcam_index_opens_with_default_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeCapture.calls = []
    monkeypatch.setattr(cv2, "VideoCapture", _FakeCapture)
    assert Cv2Source("0", target_fps=5)._open() is not None
    assert _FakeCapture.calls == [(0,)]


def test_cv2_source_logs_the_camera_without_its_password(
    caplog: pytest.LogCaptureFixture,
) -> None:
    url = "rtsp://admin:s3cr3t@127.0.0.1:1/stream2"
    source = Cv2Source(url, target_fps=5, max_reconnects=1, sleep=lambda _s: None)
    source._open = lambda: None  # type: ignore[method-assign]
    with caplog.at_level("WARNING"):
        assert source.read() is None
    assert "s3cr3t" not in caplog.text
    assert "rtsp://admin:***@127.0.0.1:1/stream2" in caplog.text


# -- latest-frame grabber ------------------------------------------------------------------


def _frame(level: int, w: int = 64, h: int = 48) -> np.ndarray:
    return np.full((h, w, 3), level, dtype=np.uint8)


class _Camera:
    """One `cv2.VideoCapture` of a live camera: `read()` blocks until the test pushes a
    frame and moves the shared fake clock to that frame's capture time. Pushing None makes
    the read fail (the stream dropped)."""

    def __init__(self, clock: list[float], opens: bool = True) -> None:
        self._clock = clock
        self._opens = opens
        self.frames: queue.Queue[tuple[float, np.ndarray] | None] = queue.Queue()
        self.released = threading.Event()

    def push(self, ts: float, image: np.ndarray) -> None:
        self.frames.put((ts, image))

    def isOpened(self) -> bool:
        return self._opens

    def set(self, *_a: object) -> bool:
        return True

    def get(self, _prop: int) -> float:
        return 0.0

    def read(self) -> tuple[bool, np.ndarray | None]:
        try:
            item = self.frames.get(timeout=0.5)  # the read timeout of a silent camera
        except queue.Empty:
            return False, None
        if item is None:
            return False, None
        self._clock[0] = item[0]
        return True, item[1]

    def release(self) -> None:
        self.released.set()


def _until(cond: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.002)


@pytest.fixture
def cameras(monkeypatch: pytest.MonkeyPatch) -> tuple[list[float], list[_Camera]]:
    """The fake clock, and the cameras `cv2.VideoCapture` hands out in order (then ones
    that fail to open)."""
    clock = [0.0]
    queued: list[_Camera] = []

    def video_capture(*_a: object) -> _Camera:
        return queued.pop(0) if queued else _Camera(clock, opens=False)

    monkeypatch.setattr(cv2, "VideoCapture", video_capture)
    return clock, queued


def _source(clock: list[float], target_fps: float) -> Cv2Source:
    return Cv2Source(
        "rtsp://u:p4ss@cam/stream2",
        target_fps,
        clock=lambda: clock[0],
        sleep=lambda _s: time.sleep(0.01),
    )


def test_read_returns_the_newest_frame_not_the_backlog(cameras: Any) -> None:
    clock, queued = cameras
    cam = _Camera(clock)
    queued.append(cam)
    source = _source(clock, target_fps=10)
    source.start()
    for i in range(5):  # a 25 fps camera while the pipeline was busy for 160 ms
        cam.push(i * 0.04, _frame(10 * i))
    _until(lambda: source.health().frames == 5)
    item = source.read()
    source.close()
    assert item is not None
    ts, image = item
    assert ts == pytest.approx(0.16)
    assert int(image.mean()) == 40


def test_read_never_returns_the_same_frame_twice(cameras: Any) -> None:
    clock, queued = cameras
    cam = _Camera(clock)
    queued.append(cam)
    source = _source(clock, target_fps=0)
    cam.push(0.0, _frame(1))
    first = source.read()
    got: list[Any] = []
    reader = threading.Thread(target=lambda: got.append(source.read()))
    reader.start()
    time.sleep(0.1)
    assert got == []  # no new frame yet: read waits instead of repeating frame 1
    cam.push(0.5, _frame(2))
    reader.join(5)
    source.close()
    assert first is not None and int(first[1].mean()) == 1
    assert got and got[0] is not None and int(got[0][1].mean()) == 2


def test_close_wakes_a_waiting_read(cameras: Any) -> None:
    clock, queued = cameras
    queued.append(_Camera(clock))
    source = _source(clock, target_fps=10)
    threading.Timer(0.1, source.close).start()
    assert source.read() is None


@pytest.mark.parametrize(
    ("due", "ts", "after"),
    [
        (-float("inf"), 0.0, 0.1),  # first frame: the next one a period later
        (0.1, 0.12, 0.2),  # on schedule: keep the grid, so 25 fps paced to 10 stays 10
        (0.1, 0.9, 1.0),  # far behind (slow pipeline, a gap): restart from this frame
    ],
)
def test_next_due_keeps_the_target_rate(due: float, ts: float, after: float) -> None:
    assert next_due(due, ts, 0.1) == pytest.approx(after)


def test_a_25fps_camera_is_paced_to_the_target_fps(cameras: Any) -> None:
    clock, queued = cameras
    cam = _Camera(clock)
    queued.append(cam)
    source = _source(clock, target_fps=10)
    out: list[float] = []

    def reader() -> None:
        while (item := source.read()) is not None:
            out.append(item[0])

    thread = threading.Thread(target=reader)
    thread.start()
    for i in range(26):  # 1 s of a 25 fps camera
        cam.push(i * 0.04, _frame(i))
        _until(lambda n=i + 1: source.health().frames == n)
        time.sleep(0.005)  # let the reader take it
    source.close()
    thread.join(5)
    assert 9 <= len(out) <= 11
    assert all(b - a >= 0.08 - 1e-9 for a, b in itertools.pairwise(out))


def test_reconnects_after_the_stream_drops(cameras: Any, caplog: pytest.LogCaptureFixture) -> None:
    clock, queued = cameras
    first, second = _Camera(clock), _Camera(clock)
    queued.extend([first, second])
    source = _source(clock, target_fps=0)
    first.push(0.0, _frame(1))
    assert source.read() is not None
    with caplog.at_level("WARNING"):
        first.frames.put(None)  # the camera rebooted
        assert first.released.wait(5)
        second.push(3.0, _frame(2))
        item = source.read()
    source.close()
    assert item is not None and int(item[1].mean()) == 2
    assert source.health().reconnects >= 1
    assert "p4ss" not in caplog.text and "u:***@cam" in caplog.text


def test_health_reports_fps_resolution_age_and_connection(cameras: Any) -> None:
    clock, queued = cameras
    cam = _Camera(clock)
    queued.append(cam)
    source = _source(clock, target_fps=5)
    assert source.health().connected is False
    assert source.health().last_frame_age_s is None
    source.start()
    for i in range(11):  # 10 fps for 1 s, 1280x720
        cam.push(i * 0.1, _frame(i, 1280, 720))
    _until(lambda: source.health().frames == 11)
    health = source.health()
    assert health.connected is True
    assert health.fps == pytest.approx(10.0)
    assert (health.width, health.height) == (1280, 720)
    assert health.last_frame_age_s == pytest.approx(0.0)
    clock[0] = 3.0
    assert source.health().last_frame_age_s == pytest.approx(2.0)
    source.close()


def test_health_is_disconnected_while_the_camera_is_unreachable(cameras: Any) -> None:
    clock, _queued = cameras  # nothing queued: every open fails
    sleeps: list[float] = []
    source = Cv2Source(
        "rtsp://cam/stream2", target_fps=5, clock=lambda: clock[0], sleep=sleeps.append
    )
    source.start()
    _until(lambda: len(sleeps) >= 5)
    health = source.health()
    source.close()
    assert health.connected is False
    assert health.reconnects >= 5
    assert sleeps[:5] == [0.5, 1.0, 2.0, 4.0, 8.0]  # exponential backoff


def test_health_names_the_codec_when_the_backend_reports_it(cameras: Any) -> None:
    clock, queued = cameras

    class H264(_Camera):
        def get(self, prop: int) -> float:
            return float(cv2.VideoWriter.fourcc(*"h264")) if prop == cv2.CAP_PROP_FOURCC else 0.0

    cam = H264(clock)
    queued.append(cam)
    source = _source(clock, target_fps=5)
    cam.push(0.0, _frame(1))
    assert source.read() is not None
    assert source.health().codec == "h264"
    source.close()
