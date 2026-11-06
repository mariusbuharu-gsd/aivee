"""Edge health numbers published on `metrics` every few seconds."""

from collections.abc import Callable

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
