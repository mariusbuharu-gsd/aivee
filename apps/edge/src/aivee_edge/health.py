"""Camera-down signal on the edge (audit V10): watch every live camera's health and report it.

`CameraHealthMonitor.tick()` runs on the supervisor's thread about once a second. It reads
`health()` from every source that has one (live `Cv2Source`; clips and cloud frames have
none), turns it into a `CameraHealth` per camera (`domain.camera_health`) and hands the result
to each `HealthSink`.

Today the only sink is `LogHealth`: `camera_down` / `camera_reconnecting` warnings when a
camera changes state, `camera_up` when it is back, and a `camera_health` summary line every
minute. The contracts carry no per-camera state yet, so nothing else in the stack can show a
single camera as down while its device is online. When they do (a per-camera field on
`DeviceStatus` or `Metrics`), an MQTT sink plugs in here; see docs/handbook/ip-cameras.md.
"""

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol

from aivee_edge.domain.camera_health import CameraHealth, CameraWatch, SourceHealth

log = logging.getLogger("aivee_edge.health")

SUMMARY_EVERY_S = 60.0


class HealthSink(Protocol):
    def report(self, every: Sequence[CameraHealth], changed: Sequence[CameraHealth]) -> None:
        """`every`: each live camera now; `changed`: those whose state just changed."""
        ...


class LogHealth:
    """`HealthSink` that writes state changes and a periodic summary to the log."""

    def __init__(
        self,
        summary_every_s: float = SUMMARY_EVERY_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._summary_every_s = summary_every_s
        self._clock = clock
        self._summary_at = -float("inf")

    def report(self, every: Sequence[CameraHealth], changed: Sequence[CameraHealth]) -> None:
        for h in changed:
            age = f"{h.last_frame_age_s:.0f}" if h.last_frame_age_s is not None else "never"
            if h.state == "ok":
                log.info("camera_up camera=%s fps=%.1f", h.camera_id, h.fps)
            else:
                log.warning("camera_%s camera=%s last_frame_age_s=%s", h.state, h.camera_id, age)
        now = self._clock()
        if every and now - self._summary_at >= self._summary_every_s:
            self._summary_at = now
            log.info("camera_health %s", " ".join(_summary(h) for h in every))


def _summary(h: CameraHealth) -> str:
    size = f"{h.width}x{h.height}" if h.width and h.height else "?"
    age = f"{h.last_frame_age_s:.1f}" if h.last_frame_age_s is not None else "never"
    return f"{h.camera_id}={h.state} fps={h.fps:.1f} size={size} age_s={age}"


class _Measured(Protocol):
    def health(self) -> SourceHealth: ...


class CameraHealthMonitor:
    def __init__(
        self,
        sources: Mapping[str, object],
        sinks: Sequence[HealthSink],
        *,
        watch: CameraWatch | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sources: dict[str, _Measured] = {
            cid: src  # type: ignore[misc]
            for cid, src in sources.items()
            if callable(getattr(src, "health", None))
        }
        self._sinks = list(sinks)
        self._watch = watch or CameraWatch()
        self._clock = clock
        self._wall = wall

    def tick(self) -> None:
        if not self._sources:
            return
        healths = {cid: src.health() for cid, src in self._sources.items()}
        every, changed = self._watch.observe(self._clock(), self._wall(), healths)
        for sink in self._sinks:
            try:
                sink.report(every, changed)
            except Exception:
                log.exception("camera health sink %s failed", type(sink).__name__)
