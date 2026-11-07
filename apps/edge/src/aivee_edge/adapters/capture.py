"""Frame sources: live cameras (phone MJPEG, RTSP, webcam) and recorded files."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

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


class Cv2Source:
    """Live source. Drops frames to `target_fps`, reconnects with exponential backoff.

    Timestamps come from `time.monotonic()`. `read()` never returns None unless
    `max_reconnects` is exceeded (live cameras do not "end").
    """

    def __init__(
        self,
        url_or_index: str | int,
        target_fps: float = 10.0,
        *,
        max_backoff_s: float = 10.0,
        max_reconnects: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        rotate: int = 0,
    ) -> None:
        rotate_check(rotate)
        self._rotate = rotate
        self._source = _parse_source(url_or_index)
        self._period = 1.0 / target_fps if target_fps > 0 else 0.0
        self._max_backoff = max_backoff_s
        self._max_reconnects = max_reconnects
        self._clock = clock
        self._sleep = sleep
        self._cap: cv2.VideoCapture | None = None
        self._last_emit = -float("inf")

    def _open(self) -> bool:
        if isinstance(self._source, str) and "://" in self._source:
            # FFmpeg's frame threading holds about one frame per decoder thread: at 5 fps on
            # 12 cores that is ~2.4 s behind the camera. One thread keeps the reader live.
            cap = cv2.VideoCapture(self._source, cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])
        else:
            cap = cv2.VideoCapture(self._source)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            cap.release()
            return False
        self._cap = cap
        return True

    def _reconnect(self) -> bool:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        backoff = 0.5
        attempts = 0
        while not self._open():
            attempts += 1
            if self._max_reconnects is not None and attempts > self._max_reconnects:
                return False
            log.warning("camera %s unavailable, retrying in %.1fs", self._source, backoff)
            self._sleep(backoff)
            backoff = min(backoff * 2, self._max_backoff)
        return True

    def read(self) -> tuple[float, Image] | None:
        while True:
            if self._cap is None and not self._reconnect():
                return None
            assert self._cap is not None
            ok, image = self._cap.read()
            if not ok or image is None:
                log.warning("camera %s read failed, reconnecting", self._source)
                self._cap.release()
                self._cap = None
                continue
            now = self._clock()
            if now - self._last_emit >= self._period:
                self._last_emit = now
                return now, rotate(image, self._rotate)
            # else: drop the frame; grabbing keeps the buffer fresh

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


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
