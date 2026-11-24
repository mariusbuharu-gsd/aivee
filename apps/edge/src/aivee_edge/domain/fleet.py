"""Which camera workers an edge box runs, from the cameras the dashboard configured for it.

The edge box (no SOURCE, no CAMERAS) runs every camera of its retained `DeviceConfig` that has
a live network source. When the config changes it starts the new cameras, stops the removed
ones and restarts those whose source changed, leaving the others alone (`plan_fleet`).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

LIVE_SCHEMES = frozenset({"rtsp", "rtsps", "http", "https"})


def is_live_source(source: str) -> bool:
    """An RTSP or HTTP stream with a host. Webcam indexes, files and cloud frames
    (`mqtt-frames://`) are not something a box reads from its network."""
    try:
        parts = urlsplit(source.strip())
    except ValueError:
        return False
    return parts.scheme.lower() in LIVE_SCHEMES and bool(parts.hostname)


def wanted_cameras(cameras: Iterable[tuple[str, str]]) -> dict[str, str]:
    """(camera id, source) pairs → id: source of the live ones."""
    return {camera_id: source for camera_id, source in cameras if is_live_source(source)}


@dataclass(frozen=True)
class FleetChanges:
    stop: list[str] = field(default_factory=list)
    """Camera ids to stop: removed from the config, or their source changed."""
    start: list[str] = field(default_factory=list)
    """Camera ids to start: new, or their source changed (stopped first)."""


def plan_fleet(
    running: Mapping[str, str],
    wanted: Mapping[str, str],
    failed: Mapping[str, str] | None = None,
) -> FleetChanges:
    """`running` and `wanted` map camera id → source. `failed` holds cameras whose worker could
    not be built for that source; they are not retried until their source changes."""
    failed = failed or {}
    stop = sorted(cid for cid, src in running.items() if wanted.get(cid) != src)
    start = sorted(
        cid for cid, src in wanted.items() if running.get(cid) != src and failed.get(cid) != src
    )
    return FleetChanges(stop=stop, start=start)
