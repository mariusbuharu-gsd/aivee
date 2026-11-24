"""Frame sources: live cameras (phone MJPEG, RTSP, webcam) and recorded files."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from aivee_edge.domain.camera_health import SourceHealth
from aivee_edge.redact import redact_url

log = logging.getLogger(__name__)

Image = np.ndarray


_ROTATIONS: dict[int, int | None] = {
    0: None,
    90: cv2.ROTATE_90_CLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}


def rotate(image: Image, degrees: int) -> Image:
    """Turn `image` clockwise by 0/90/180/270 degrees.

    Applied right after capture, so detection, zones (normalised against the rotated frame),
    snapshots and live detections all see the upright picture.
    """
    rotate_check(degrees)
    code = _ROTATIONS[degrees]
    return image if code is None else cv2.rotate(image, code)


def rotate_check(degrees: int) -> None:
    if degrees not in _ROTATIONS:
        raise ValueError(f"rotation must be one of {sorted(_ROTATIONS)}, got {degrees}")


def _parse_source(url_or_index: str | int) -> str | int:
    if isinstance(url_or_index, str) and url_or_index.isdigit():
        return int(url_or_index)
    return url_or_index


FFMPEG_OPTIONS_ENV = "OPENCV_FFMPEG_CAPTURE_OPTIONS"
FPS_WINDOW_S = 5.0
"""Measured camera fps counts the frames decoded over this many seconds."""
FIRST_BACKOFF_S = 0.5
_WAIT_SLICE_S = 0.25
"""`read()` and the grabber re-check `close()` at least this often."""


def next_due(due: float, ts: float, period: float) -> float:
    """When the frame after one emitted at `ts` is due, given the previous due time.

    On schedule, the next frame is due a period after the previous due time (not after
    `ts`), so a 25 fps camera paced to 10 fps gives 10 frames a second, not 8.3. A frame
    more than a period late (a slow pipeline, a stream gap) restarts the schedule.
    """
    return due + period if ts - due < period else ts + period


def ffmpeg_capture_options(timeout_s: float) -> None:
    """RTSP over TCP and a socket I/O timeout for every FFmpeg capture in this process.

    OpenCV reads `OPENCV_FFMPEG_CAPTURE_OPTIONS` on each open. A value the operator already
    set is kept as is, so a camera that needs UDP can still be served.
    """
    os.environ.setdefault(
        FFMPEG_OPTIONS_ENV, f"rtsp_transport;tcp|timeout;{round(timeout_s * 1_000_000)}"
    )


def fourcc(value: float) -> str | None:
    """`CAP_PROP_FOURCC` as text (`h264`, `hevc`, `MJPG`), None when the backend gives 0."""
    code = int(value)
    if code <= 0:
        return None
    text = code.to_bytes(4, "little").decode("ascii", "replace").strip("\x00 ")
    return text or None


@dataclass(frozen=True)
class _Grabbed:
    seq: int
    ts: float
    image: Image


class Cv2Source:
    """Live source (RTSP, HTTP MJPEG, webcam) read by a grabber thread that keeps only
    the newest decoded frame.

    The camera is read at its own rate on a background thread, so a 25 fps camera never
    builds a backlog behind a slower pipeline. `read()` returns the newest frame once it is
    due at `target_fps` (see `next_due`), never an older one and never the same one twice;
    it waits while there is no new frame (a stalled or reconnecting camera). Timestamps
    are `clock()` at decode time. The stream reconnects with exponential backoff; `read()`
    returns None only after `max_reconnects` failed opens in a row, or after `close()`.

    Network URLs use RTSP over TCP and open/read timeouts of `timeout_s`. `health()` says
    how the stream is doing (see `SourceHealth`).
    """

    def __init__(
        self,
        url_or_index: str | int,
        target_fps: float = 10.0,
        *,
        max_backoff_s: float = 10.0,
        max_reconnects: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] | None = None,
        rotate: int = 0,
        timeout_s: float = 5.0,
    ) -> None:
        rotate_check(rotate)
        self._rotate = rotate
        self._source = _parse_source(url_or_index)
        self._shown = redact_url(self._source)
        self._period = 1.0 / target_fps if target_fps > 0 else 0.0
        self._max_backoff = max_backoff_s
        self._max_reconnects = max_reconnects
        self._clock = clock
        self._closed = threading.Event()
        # Default: a backoff that close() can cut short.
        self._sleep = sleep or (lambda s: self._closed.wait(s) and None)
        self._timeout_s = timeout_s

        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None
        self._latest: _Grabbed | None = None
        self._emitted = 0  # seq of the frame read() returned last
        self._due = -float("inf")
        self._ended = False
        self._connected = False
        self._frames = 0
        self._reconnects = 0
        self._stamps: deque[float] = deque()
        self._size: tuple[int, int] | None = None
        self._codec: str | None = None

    # -- grabber thread ------------------------------------------------------------

    def start(self) -> None:
        """Start grabbing (`read()` does it on first use)."""
        with self._cond:
            if self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._grab, name=f"grab {self._shown}", daemon=True
            )
        self._thread.start()

    def _open(self) -> Any:
        """An opened `cv2.VideoCapture`, or None."""
        if isinstance(self._source, str) and "://" in self._source:
            ffmpeg_capture_options(self._timeout_s)
            timeout_ms = round(self._timeout_s * 1000)
            # FFmpeg's frame threading holds about one frame per decoder thread: at 5 fps on
            # 12 cores that is ~2.4 s behind the camera. One thread keeps the reader live.
            params = [
                cv2.CAP_PROP_N_THREADS,
                1,
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                timeout_ms,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                timeout_ms,
            ]
            cap = cv2.VideoCapture(self._source, cv2.CAP_FFMPEG, params)
        else:
            cap = cv2.VideoCapture(self._source)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            cap.release()
            return None
        return cap

    def _connect(self) -> Any:
        """Open the stream, backing off between failed attempts; None to give up."""
        backoff = FIRST_BACKOFF_S
        attempts = 0
        while not self._closed.is_set():
            cap = self._open()
            if cap is not None:
                return cap
            attempts += 1
            with self._cond:
                self._reconnects += 1
            if self._max_reconnects is not None and attempts > self._max_reconnects:
                return None
            log.warning("camera %s unavailable, retrying in %.1fs", self._shown, backoff)
            self._sleep(backoff)
            backoff = min(backoff * 2, self._max_backoff)
        return None

    def _grab(self) -> None:
        cap: Any = None
        try:
            while not self._closed.is_set():
                if cap is None:
                    cap = self._connect()
                    if cap is None:
                        break
                    codec = fourcc(cap.get(cv2.CAP_PROP_FOURCC))
                    with self._cond:
                        self._codec = codec
                ok, image = cap.read()
                if self._closed.is_set():
                    break
                if not ok or image is None:
                    log.warning("camera %s read failed, reconnecting", self._shown)
                    cap.release()
                    cap = None
                    with self._cond:
                        self._connected = False
                        self._reconnects += 1
                    continue
                self._keep(image)
        finally:
            if cap is not None:
                cap.release()
            with self._cond:
                self._ended = True
                self._connected = False
                self._cond.notify_all()

    def _keep(self, image: Image) -> None:
        ts = self._clock()
        with self._cond:
            self._frames += 1
            self._latest = _Grabbed(self._frames, ts, image)
            self._connected = True
            self._size = (int(image.shape[1]), int(image.shape[0]))
            self._stamps.append(ts)
            while self._stamps and self._stamps[0] < ts - FPS_WINDOW_S:
                self._stamps.popleft()
            self._cond.notify_all()

    # -- FrameSource -----------------------------------------------------------------

    def read(self) -> tuple[float, Image] | None:
        self.start()
        with self._cond:
            while True:
                frame = self._latest
                if frame is not None and frame.seq > self._emitted and frame.ts >= self._due:
                    break
                if self._ended or self._closed.is_set():
                    return None
                self._cond.wait(_WAIT_SLICE_S)
            self._emitted = frame.seq
            self._due = next_due(self._due, frame.ts, self._period)
        return frame.ts, rotate(frame.image, self._rotate)

    def ended(self) -> bool:
        """The grabber stopped: closed, or it gave up after `max_reconnects`."""
        with self._cond:
            return self._ended

    def health(self) -> SourceHealth:
        now = self._clock()
        with self._cond:
            latest = self._latest
            stamps = [t for t in self._stamps if t >= now - FPS_WINDOW_S]
            span = stamps[-1] - stamps[0] if len(stamps) > 1 else 0.0
            return SourceHealth(
                connected=self._connected,
                last_frame_age_s=max(0.0, now - latest.ts) if latest is not None else None,
                fps=round((len(stamps) - 1) / span, 2) if span > 0 else 0.0,
                width=self._size[0] if self._size else None,
                height=self._size[1] if self._size else None,
                frames=self._frames,
                reconnects=self._reconnects,
                codec=self._codec,
            )

    def close(self) -> None:
        """Stop grabbing; a waiting `read()` returns None. The thread is a daemon: a read
        stuck in FFmpeg ends at the read timeout."""
        self._closed.set()
        with self._cond:
            self._cond.notify_all()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)


class FileSource:
    """Recorded clip. Samples frames at `target_fps` of video time.

    Never sleeps: a clip is decoded and analysed as fast as the CPU allows, while the
    timestamps stay in video time, so durations in rules mean seconds of the clip.

    Timestamps are video positions in seconds (frame index / native fps), plus an
    offset per loop so they stay monotonic when `loop=True`.
    """

    def __init__(
        self, path: str | Path, target_fps: float = 10.0, loop: bool = False, *, rotate: int = 0
    ) -> None:
        rotate_check(rotate)
        self._rotate = rotate
        self._path = str(path)
        self._cap = cv2.VideoCapture(self._path)
        if not self._cap.isOpened():
            raise FileNotFoundError(f"cannot open video {self._path}")
        native = self._cap.get(cv2.CAP_PROP_FPS)
        self._native_fps = native if native and native > 0 else 30.0
        self._period = 1.0 / target_fps if target_fps > 0 else 0.0
        self._loop = loop
        self._index = 0  # frame index within the current pass
        self._offset = 0.0  # seconds added per completed loop
        self._next_ts = 0.0

    @property
    def native_fps(self) -> float:
        return self._native_fps

    @property
    def duration_s(self) -> float | None:
        """Length of one pass in seconds (frame count / native fps), None if unknown."""
        count = self._cap.get(cv2.CAP_PROP_FRAME_COUNT)
        return count / self._native_fps if count and count > 0 else None

    def read(self) -> tuple[float, Image] | None:
        while True:
            ok, image = self._cap.read()
            if not ok or image is None:
                if not self._loop or self._index == 0:
                    return None
                self._offset += self._index / self._native_fps
                self._index = 0
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            ts = self._offset + self._index / self._native_fps
            self._index += 1
            # small epsilon so 30 fps -> 10 fps keeps exactly every 3rd frame
            if ts + 1e-6 >= self._next_ts:
                self._next_ts = ts + self._period
                return ts, rotate(image, self._rotate)

    def close(self) -> None:
        self._cap.release()
