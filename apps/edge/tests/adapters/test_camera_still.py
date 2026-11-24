"""The camera test: ask the camera why it would not stream (fake sockets), grab one frame (a
fake capture), blur it and send a JPEG. No camera, no network."""

from datetime import UTC, datetime
from typing import Any

import numpy as np
import pytest
from aivee_edge.adapters.camera_still import (
    CameraTester,
    CameraTestError,
    grab_still,
    probe_stream,
)
from aivee_edge.domain.camera_health import SourceHealth


class FakeSock:
    """One TCP connection: records what was sent and returns one canned answer."""

    def __init__(self, answer: bytes) -> None:
        self.answer = answer
        self.sent = b""

    def __enter__(self) -> "FakeSock":
        return self

    def __exit__(self, *_a: Any) -> None: ...

    def settimeout(self, _t: float) -> None: ...

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def recv(self, _n: int) -> bytes:
        out, self.answer = self.answer, b""
        return out


def _camera(*answers: bytes) -> tuple[Any, list[FakeSock]]:
    """A `connect` that opens one FakeSock per answer, in order."""
    opened: list[FakeSock] = []

    def connect(_addr: tuple[str, int], timeout: float) -> FakeSock:
        sock = FakeSock(answers[len(opened)])
        opened.append(sock)
        return sock

    return connect, opened


CHALLENGE = (
    b"RTSP/1.0 401 Unauthorized\r\nCSeq: 1\r\n"
    b'WWW-Authenticate: Digest realm="C210", nonce="0f1e2d"\r\n\r\n'
)


def test_wrong_password_is_auth() -> None:
    connect, opened = _camera(CHALLENGE, b"RTSP/1.0 401 Unauthorized\r\nCSeq: 2\r\n\r\n")
    assert probe_stream("rtsp://admin:wrong@192.168.1.21:554/stream2", connect=connect) == "auth"
    first, second = (s.sent.decode() for s in opened)
    assert "Authorization" not in first and "Authorization: Digest" in second
    assert "wrong" not in first + second  # Digest never sends the password itself


def test_right_password_and_a_wrong_path() -> None:
    connect, _ = _camera(CHALLENGE, b"RTSP/1.0 200 OK\r\nCSeq: 2\r\n\r\n")
    assert probe_stream("rtsp://admin:pw@192.168.1.21/stream2", connect=connect) == "ok"
    connect, _ = _camera(CHALLENGE, b"RTSP/1.0 404 Not Found\r\nCSeq: 2\r\n\r\n")
    assert probe_stream("rtsp://admin:pw@192.168.1.21/stream9", connect=connect) == "no_stream"


def test_no_credentials_on_a_camera_that_wants_them_is_auth() -> None:
    connect, opened = _camera(CHALLENGE)
    assert probe_stream("rtsp://192.168.1.21/stream2", connect=connect) == "auth"
    assert len(opened) == 1


@pytest.mark.parametrize("error", [ConnectionRefusedError(), TimeoutError(), OSError("no route")])
def test_no_answer_at_that_address_is_unreachable(error: Exception) -> None:
    def connect(_addr: tuple[str, int], timeout: float) -> FakeSock:
        raise error

    assert probe_stream("rtsp://admin:pw@192.168.1.99/stream2", connect=connect) == "unreachable"


def test_something_that_is_not_rtsp_is_unknown() -> None:
    connect, _ = _camera(b"SSH-2.0-OpenSSH_9.6\r\n")
    assert probe_stream("rtsp://admin:pw@192.168.1.21:22/x", connect=connect) == "unknown"
    assert probe_stream("0") == "unknown"


def test_an_mjpeg_camera_is_asked_over_http_with_basic() -> None:
    connect, opened = _camera(
        b'HTTP/1.1 401 Unauthorized\r\nWWW-Authenticate: Basic realm="cam"\r\n\r\n',
        b"HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace\r\n\r\n",
    )
    assert probe_stream("http://admin:pw@192.168.1.40:8080/video", connect=connect) == "ok"
    assert opened[1].sent.startswith(b"GET /video HTTP/1.1")


class FakeCapture:
    """Cv2Source stand-in: `frames` decoded after `after` health polls."""

    def __init__(self, image: Any | None, after: int = 2, ends: bool = False) -> None:
        self.image, self.after, self.ends = image, after, ends
        self.polls = 0
        self.closed = False

    def start(self) -> None: ...

    def health(self) -> SourceHealth:
        self.polls += 1
        got = self.image is not None and self.polls > self.after
        return SourceHealth(got, 0.0 if got else None, 0.0, frames=int(got))

    def ended(self) -> bool:
        return self.ends

    def read(self) -> tuple[float, Any]:
        return 1.0, self.image

    def close(self) -> None:
        self.closed = True


def test_grab_still_waits_for_the_first_frame_then_closes() -> None:
    image = np.zeros((360, 640, 3), np.uint8)
    cap = FakeCapture(image)
    assert grab_still("rtsp://x", 6.0, open_source=lambda *_a: cap, sleep=lambda _s: None) is image
    assert cap.closed


def test_grab_still_gives_up_at_the_timeout_or_when_the_source_ends() -> None:
    now = [0.0]

    def sleep(s: float) -> None:
        now[0] += s

    cap = FakeCapture(None)
    got = grab_still(
        "rtsp://x", 6.0, open_source=lambda *_a: cap, clock=lambda: now[0], sleep=sleep
    )
    assert got is None and cap.closed and 6.0 <= now[0] < 6.5
    ended = FakeCapture(None, ends=True)
    assert grab_still("rtsp://x", 6.0, open_source=lambda *_a: ended, sleep=sleep) is None


class Blur:
    def __init__(self) -> None:
        self.seen: list[Any] = []

    def blur(self, image: Any) -> Any:
        self.seen.append(image)
        return image + 1


AT = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def _tester(probe: str, image: Any | None, blur: Any = None, **kw: Any) -> CameraTester:
    blurrer = blur or Blur()
    return CameraTester(
        lambda: blurrer,
        lambda img: b"\xff\xd8" + bytes([int(img.flat[0])]) + f"{img.shape[1]}".encode(),
        probe=lambda _src, _t: probe,
        grab=lambda _src, _t: image,
        clock=lambda: AT,
        **kw,
    )


def test_a_working_camera_gives_a_blurred_jpeg_and_its_size() -> None:
    image = np.zeros((720, 1280, 3), np.uint8)
    blur = Blur()
    still = _tester("ok", image, blur).test("rtsp://admin:pw@192.168.1.21/stream2")
    assert (still.width, still.height, still.at) == (1280, 720, AT)
    assert still.jpeg == b"\xff\xd8\x011280"  # blurred (+1) before encoding
    assert len(blur.seen) == 1


def test_a_big_frame_is_scaled_down_but_reports_the_stream_size() -> None:
    image = np.zeros((1440, 2560, 3), np.uint8)
    still = _tester("unknown", image).test("rtsp://admin:pw@192.168.1.21/stream1")
    assert (still.width, still.height) == (2560, 1440)
    assert still.jpeg.endswith(b"1280")


@pytest.mark.parametrize(
    ("probe", "image", "code"),
    [
        ("auth", None, "camera_auth"),
        ("unreachable", None, "camera_unreachable"),
        ("no_stream", None, "camera_no_stream"),
        ("ok", None, "camera_no_stream"),  # it answered, but no frame came
        ("unknown", None, "camera_no_stream"),
    ],
)
def test_failures_have_a_code(probe: str, image: Any, code: str) -> None:
    with pytest.raises(CameraTestError) as e:
        _tester(probe, image).test("rtsp://admin:pw@192.168.1.21/stream2")
    assert e.value.code == code
    assert "pw" not in str(e.value)


def test_a_source_that_is_not_a_network_stream_is_a_bad_request() -> None:
    with pytest.raises(CameraTestError) as e:
        _tester("ok", None).test("mqtt-frames://cam-01")
    assert e.value.code == "bad_request"


def test_no_blur_no_picture() -> None:
    class Broken:
        def blur(self, _image: Any) -> Any:
            raise RuntimeError("yunet missing")

    with pytest.raises(CameraTestError) as e:
        _tester("ok", np.zeros((4, 4, 3), np.uint8), Broken()).test("rtsp://h/s")
    assert e.value.code == "failed"
