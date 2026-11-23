"""How a live camera stream is doing, and when it counts as down (audit V10).

`SourceHealth` is what the capture adapter measures. `CameraWatch` turns the health of every
camera of a device into a `CameraHealth` per camera with a `state`:

- `ok`: frames are arriving.
- `reconnecting`: the stream dropped or does not open; the grabber is retrying.
- `down`: no frame for more than `DOWN_AFTER_S` (reconnecting or not: a frozen stream that
  stays connected is down too), or none at all within `DOWN_AFTER_S` of the start.

The names (`state`, `last_frame_at`, `fps`) match what the dashboard expects per camera once
the contracts carry them; see docs/handbook/ip-cameras.md.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

DOWN_AFTER_S = 60.0

StreamState = Literal["ok", "reconnecting", "down"]


@dataclass(frozen=True)
class SourceHealth:
    """A snapshot of one live source.

    `connected`: the stream is open and its last read succeeded (False while reconnecting).
    `last_frame_age_s`: seconds since the newest decoded frame, None before the first one.
    `fps`: frames the camera delivered per second over the last few seconds (before any
    drop to the pipeline's target fps). `width`/`height`: of the camera picture, before
    rotation; None before the first frame. `frames`: decoded since start. `reconnects`:
    failed opens and dropped streams since start.
    """

    connected: bool
    last_frame_age_s: float | None
    fps: float
    width: int | None = None
    height: int | None = None
    frames: int = 0
    reconnects: int = 0
    codec: str | None = None
    """FourCC the backend reports for the stream (e.g. `h264`), None when it says nothing."""


@dataclass(frozen=True)
class CameraHealth:
    """One camera's state as the rest of the stack should see it."""

    camera_id: str
    state: StreamState
    last_frame_at: datetime | None
    last_frame_age_s: float | None
    fps: float
    width: int | None = None
    height: int | None = None


def stream_state(
    health: SourceHealth, running_s: float, down_after_s: float = DOWN_AFTER_S
) -> StreamState:
    """`running_s`: how long this camera has been watched (stands in for the frame age
    before the first frame)."""
    age = health.last_frame_age_s if health.last_frame_age_s is not None else running_s
    if age > down_after_s:
        return "down"
    return "ok" if health.connected else "reconnecting"


class CameraWatch:
    """Tracks each camera's state between observations and reports the changes."""

    def __init__(self, down_after_s: float = DOWN_AFTER_S) -> None:
        self._down_after_s = down_after_s
        self._first_seen: dict[str, float] = {}
        self._states: dict[str, StreamState] = {}

    def observe(
        self, now: float, wall: datetime, healths: Mapping[str, SourceHealth]
    ) -> tuple[list[CameraHealth], list[CameraHealth]]:
        """(every camera, the cameras whose state changed). `now` is monotonic seconds,
        `wall` the same instant as a datetime (for `last_frame_at`). A camera seen for the
        first time counts as previously `ok`."""
        every: list[CameraHealth] = []
        changed: list[CameraHealth] = []
        for camera_id, h in healths.items():
            started = self._first_seen.setdefault(camera_id, now)
            state = stream_state(h, now - started, self._down_after_s)
            age = h.last_frame_age_s
            report = CameraHealth(
                camera_id=camera_id,
                state=state,
                last_frame_at=wall - timedelta(seconds=age) if age is not None else None,
                last_frame_age_s=age,
                fps=h.fps,
                width=h.width,
                height=h.height,
            )
            every.append(report)
            if self._states.get(camera_id, "ok") != state:
                changed.append(report)
            self._states[camera_id] = state
        return every, changed
