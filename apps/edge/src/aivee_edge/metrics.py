"""Edge health numbers published on `metrics` every few seconds."""

import time
from collections.abc import Callable, Sequence

from aivee_contracts.events import Metrics


def cpu_percent() -> float:
    """System CPU use since the previous call (psutil), or 0.0 when psutil is missing."""
    try:
        import psutil  # type: ignore[import-untyped, import-not-found, unused-ignore]
    except ImportError:
        return 0.0
    return float(psutil.cpu_percent(interval=None))


class MetricsMeter:
    """Counts frames on frame time and yields a `Metrics` once per `interval_s`.

    `verified_ratio` is the share of frames that ran the heavy optional stages
    (pose, appearance embedding).
    """

    def __init__(
        self,
        device: str,
        interval_s: float = 5.0,
        cpu: Callable[[], float] = cpu_percent,
    ) -> None:
        self._device = device
        self._interval_s = interval_s
        self._cpu = cpu
        self._since: float | None = None
        self._frames = 0
        self._verified = 0

    def record(self, ts: float, verified: bool) -> Metrics | None:
        if self._since is None:
            # The first frame only starts the clock; frames are counted after it.
            self._since = ts
            self._cpu()  # prime psutil: its first reading is meaningless
            return None
        self._frames += 1
        self._verified += verified
        elapsed = ts - self._since
        if elapsed < self._interval_s:
            return None
        metrics = Metrics(
            device=self._device,
            fps=round(self._frames / elapsed, 2),
            verified_ratio=round(self._verified / self._frames, 3),
            cpu_percent=self._cpu(),
        )
        self._since, self._frames, self._verified = ts, 0, 0
        return metrics


class DeviceMetrics:
    """Combines the Metrics of each camera's pipeline into one Metrics per device.

    The API and ingest key metrics by device (the topic has no camera), so one message per
    camera would overwrite the other. A combined Metrics goes out once every camera has
    reported since the last one (at least `interval_s` apart), or after `stale_after_s`
    whatever has arrived. `fps` is the slowest camera's, and a camera with no sample for
    `stale_after_s` (down, reconnecting) counts as 0, so a stalled camera shows. While every
    camera is silent nothing is published, and the dashboard marks the device "fără imagine"
    after 60 s, as it does for a single camera.
    """

    def __init__(
        self,
        device: str,
        cameras: Sequence[str],
        interval_s: float = 5.0,
        stale_after_s: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._device = device
        self._cameras = list(cameras)
        self._interval_s = interval_s
        self._stale_after_s = stale_after_s if stale_after_s is not None else 3 * interval_s
        self._clock = clock
        self._latest: dict[str, tuple[float, Metrics]] = {}
        self._reported: set[str] = set()
        self._published_at = clock()

    def add(self, camera_id: str, metrics: Metrics) -> Metrics | None:
        """Take one camera's sample; returns the device's Metrics when one is due."""
        if camera_id not in self._cameras:
            return None
        now = self._clock()
        self._latest[camera_id] = (now, metrics)
        self._reported.add(camera_id)
        elapsed = now - self._published_at
        everyone = self._reported >= set(self._cameras)
        if elapsed < self._interval_s or (not everyone and elapsed < self._stale_after_s):
            return None
        fresh = {cam: m for cam, (at, m) in self._latest.items() if now - at <= self._stale_after_s}
        combined = Metrics(
            device=self._device,
            fps=min(fresh[c].fps if c in fresh else 0.0 for c in self._cameras),
            verified_ratio=round(sum(m.verified_ratio for m in fresh.values()) / len(fresh), 3),
            cpu_percent=metrics.cpu_percent,
        )
        self._published_at = now
        self._reported.clear()
        return combined
