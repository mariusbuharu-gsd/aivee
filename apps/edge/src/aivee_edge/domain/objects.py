"""Per-zone object presence counted per class, with hysteresis, for `object_gone`.

Each class has a stable *level*: the highest count seen in the last `confirm_s`
seconds. A short detector gap (a glass missed for a second, an arm in front of it)
does not lower the level. When the level drops below k, the k-th object of that class
is recorded as gone, with how long it had been there and when it was last seen.

A gone record holds for `hold_s` after the confirm window, then expires; it is cleared
at once when the count is back to k (the object reappeared). An object must have been
seen for at least `confirm_s` before its disappearance counts at all.
"""

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

GONE_CONFIRM_S = 3.0
"""An object missing this long is gone (shorter gaps are detector flicker)."""
GONE_HOLD_S = 30.0
"""A gone alert stays open this long after it fired unless the object comes back."""

OBJECT_RO: dict[str, str] = {
    "wine glass": "paharul de vin",
    "cup": "ceașca",
    "bottle": "sticla",
    "bowl": "castronul",
    "fork": "furculița",
    "knife": "cuțitul",
    "spoon": "lingura",
}


def object_ro(label: str) -> str:
    """Romanian name (with article) of a COCO class, for alert texts."""
    return OBJECT_RO.get(label, f"un obiect ({label})")


@dataclass(frozen=True)
class Gone:
    label: str
    level: int
    present_s: float
    last_seen: float


class ObjectPresence:
    def __init__(self, confirm_s: float = GONE_CONFIRM_S, hold_s: float = GONE_HOLD_S) -> None:
        self.confirm_s = confirm_s
        self.hold_s = hold_s
        self._history: dict[str, deque[tuple[float, int]]] = {}
        self._since: dict[str, dict[int, float]] = {}
        self._last: dict[str, dict[int, float]] = {}
        self._gone: list[Gone] = []
        self._raw: Mapping[str, int] = {}

    def update(self, ts: float, counts: Mapping[str, int]) -> None:
        """This frame's object count per class inside the zone."""
        self._raw = counts
        for label in set(self._history) | {k for k, v in counts.items() if v > 0}:
            raw = counts.get(label, 0)
            history = self._history.setdefault(label, deque())
            history.append((ts, raw))
            while history and ts - history[0][0] >= self.confirm_s:
                history.popleft()
            level = max((c for _, c in history), default=0)
            since = self._since.setdefault(label, {})
            last = self._last.setdefault(label, {})
            for k in range(1, raw + 1):
                last[k] = ts
            for k in range(1, level + 1):
                since.setdefault(k, ts)
            for k in sorted(k for k in since if k > level):
                self._gone.append(Gone(label, k, last[k] - since[k], last[k]))
                del since[k], last[k]
            if not since and level == 0:
                del self._history[label], self._since[label], self._last[label]
        expiry = self.confirm_s + self.hold_s
        self._gone = [
            g for g in self._gone if counts.get(g.label, 0) < g.level and ts - g.last_seen <= expiry
        ]

    def gone(self, labels: Iterable[str], min_present_s: float, now: float) -> Gone | None:
        """The latest still-holding disappearance of one of `labels` that had been there
        for at least `min_present_s` (and at least the confirm window)."""
        wanted = set(labels)
        floor = max(min_present_s, self.confirm_s)
        expiry = self.confirm_s + self.hold_s
        found = [
            g
            for g in self._gone
            if g.label in wanted and g.present_s >= floor and now - g.last_seen <= expiry
        ]
        return max(found, key=lambda g: g.last_seen, default=None)

    def all_in_view(self) -> bool:
        """True when this frame shows every object the zone is believed to hold: the frame
        to keep as the "before" image of a later disappearance."""
        return all(self._raw.get(label, 0) >= max(s, default=0) for label, s in self._since.items())
