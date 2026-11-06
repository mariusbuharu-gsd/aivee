from dataclasses import dataclass
from datetime import UTC, datetime

from aivee_contracts.events import Metrics


@dataclass(frozen=True)
class MetricsSample:
    site: str
    metrics: Metrics
    received_at: datetime


class MetricsCache:
    """Latest Metrics per device, fed by the API's MQTT subscription (metrics are not stored)."""

    def __init__(self) -> None:
        self._latest: dict[str, MetricsSample] = {}

    def put(self, site: str, metrics: Metrics, at: datetime | None = None) -> None:
        self._latest[metrics.device] = MetricsSample(site, metrics, at or datetime.now(UTC))

    def latest(self) -> list[MetricsSample]:
        return [self._latest[d] for d in sorted(self._latest)]
