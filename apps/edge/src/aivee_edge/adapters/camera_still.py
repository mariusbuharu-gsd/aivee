"""The dashboard's "Testează": open a camera once and send back one face-blurred still.

1. Ask the camera (`probe_stream`, about 2 s): one RTSP DESCRIBE (HTTP GET for MJPEG), with
   Digest or Basic authentication after a 401 (`domain.stream_probe`). No answer at the
   address → `camera_unreachable`; the login refused → `camera_auth`; no stream at that path
   → `camera_no_stream`. The camera sees at most two short requests, never the password in
   clear with Digest.
2. Otherwise grab one frame with the edge's own capture (`Cv2Source`: RTSP over TCP, the
   test's timeout, 6 s by default). No frame in time → `camera_no_stream`.
3. Blur faces with the edge's blurrer, scale down to at most 1280 px wide, encode JPEG. No
   blur, no picture: a blurrer that fails gives `failed`, never an unblurred image.

The URL (with its password) is never logged.
"""

from __future__ import annotations

import logging
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from aivee_contracts.commands import ReplyError

from aivee_edge.domain.fleet import is_live_source
from aivee_edge.domain.stream_probe import (
    Response,
    StreamTarget,
    Verdict,
    authorization,
    digest_uri,
    method,
    parse_response,
    request,
    verdict,
)

log = logging.getLogger("aivee_edge.camera_still")

PROBE_S = 2.0
GRAB_S = 6.0
MAX_WIDTH = 1280
_POLL_S = 0.05
_MAX_HEAD = 16 * 1024

ProbeVerdict = Verdict | Literal["unreachable"]


class CameraTestError(Exception):
    """The test failed for a reason the dashboard can explain (`code`)."""

    def __init__(self, code: ReplyError) -> None:
        super().__init__(code)
        self.code: ReplyError = code


def _exchange(sock: Any, data: bytes) -> Response | None:
    sock.sendall(data)
    head = b""
    while b"\r\n\r\n" not in head and len(head) < _MAX_HEAD:
        chunk = sock.recv(4096)
        if not chunk:
            break
        head += chunk
    return parse_response(head)


def probe_stream(
    source: str,
    timeout_s: float = PROBE_S,
    *,
    connect: Callable[..., Any] = socket.create_connection,
) -> ProbeVerdict:
    """What the camera says about `source` (see the module docstring); "unknown" when it
    cannot tell (TLS, an odd answer) and the capture should just try."""
    target = StreamTarget.parse(source)
    if target is None:
        return "unknown"
    addr = (target.host, target.port)
    try:
        first_sock = connect(addr, timeout=timeout_s)
    except OSError:  # refused, timed out, no route
        return "unreachable"
    if target.scheme in ("https", "rtsps"):
        first_sock.close()
        return "unknown"
    try:
        with first_sock as sock:
            sock.settimeout(timeout_s)
            first = _exchange(sock, request(target, 1))
        if first is None:
            return "unknown"
        if first.status != 401:
            return verdict(first.status)
        if not target.user:
            return "auth"
        auth = authorization(
            first.challenges,
            target.user,
            target.password or "",
            method(target),
            digest_uri(target),
        )
        if auth is None:
            return "unknown"
        # A new connection: some cameras close it after a 401.
        with connect(addr, timeout=timeout_s) as sock:
            sock.settimeout(timeout_s)
            second = _exchange(sock, request(target, 2, auth))
    except OSError:
        return "unknown"
    return verdict(second.status) if second is not None else "unknown"


class _Capture(Protocol):
    def start(self) -> None: ...

    def health(self) -> Any: ...

    def ended(self) -> bool: ...

    def read(self) -> tuple[float, Any] | None: ...

    def close(self) -> None: ...


def _open_capture(source: str, timeout_s: float) -> _Capture:
    from aivee_edge.adapters.capture import Cv2Source

    return Cv2Source(source, target_fps=0, max_reconnects=0, timeout_s=timeout_s)


def grab_still(
    source: str,
    timeout_s: float = GRAB_S,
    *,
    open_source: Callable[[str, float], _Capture] = _open_capture,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Any | None:
    """The first frame the camera sends within `timeout_s`, or None."""
    cap = open_source(source, timeout_s)
    deadline = clock() + timeout_s
    try:
        cap.start()
        while clock() < deadline:
            if cap.health().frames > 0:
                frame = cap.read()
                return frame[1] if frame is not None else None
            if cap.ended():
                return None
            sleep(_POLL_S)
        return None
    finally:
        cap.close()


@dataclass(frozen=True)
class Still:
    jpeg: bytes
    width: int
    """Of the camera's stream (the JPEG may be scaled down)."""
    height: int
    at: datetime


class Blurrer(Protocol):
    def blur(self, image: Any) -> Any: ...


_FAILURES: dict[str, ReplyError] = {
    "auth": "camera_auth",
    "unreachable": "camera_unreachable",
    "no_stream": "camera_no_stream",
}


def _scaled(image: Any, max_width: int) -> Any:
    height, width = image.shape[:2]
    if width <= max_width:
        return image
    import cv2

    size = (max_width, round(height * max_width / width))
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


class CameraTester:
    def __init__(
        self,
        blurrer: Callable[[], Blurrer],
        encode: Callable[[Any], bytes],
        *,
        timeout_s: float = GRAB_S,
        probe_timeout_s: float = PROBE_S,
        max_width: int = MAX_WIDTH,
        probe: Callable[[str, float], ProbeVerdict] = probe_stream,
        grab: Callable[[str, float], Any | None] = grab_still,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """`blurrer` makes a face blurrer per test (OpenCV detectors are not thread-safe)."""
        self._blurrer = blurrer
        self._encode = encode
        self._timeout_s = timeout_s
        self._probe_timeout_s = probe_timeout_s
        self._max_width = max_width
        self._probe = probe
        self._grab = grab
        self._clock = clock

    def test(self, source: str) -> Still:
        """One blurred still of `source`; raises `CameraTestError` with the reason."""
        if not is_live_source(source):
            raise CameraTestError("bad_request")
        said = self._probe(source, self._probe_timeout_s)
        if said in _FAILURES:
            raise CameraTestError(_FAILURES[said])
        image = self._grab(source, self._timeout_s)
        if image is None:
            raise CameraTestError("camera_no_stream")
        at = self._clock()
        height, width = image.shape[:2]
        try:
            blurred = self._blurrer().blur(image)
            jpeg = self._encode(_scaled(blurred, self._max_width))
        except Exception as e:
            log.error("camera_test_blur_failed: %s", type(e).__name__)
            raise CameraTestError("failed") from None
        return Still(jpeg=bytes(jpeg), width=int(width), height=int(height), at=at)
