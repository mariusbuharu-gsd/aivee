"""Per-zone presence, absence and objects over time.

A person is in a zone when their foot point is inside its polygon; an object when
its box centre is. Durations are measured on `Frame.ts` (seconds). A role or object
missing for at most `grace_s` still counts as present, so a detector that drops a
person for a frame does not reset their timers.
"""

from aivee_contracts.geometry import Zone
from aivee_contracts.rules import Role

from aivee_edge.domain.geometry import box_centre, foot_point, point_in_polygon
from aivee_edge.domain.observation import Frame, TrackObs

ROLES: tuple[Role, ...] = ("guest", "staff", "any")


def _has_role(track: TrackObs, role: Role) -> bool:
    return role == "any" or track.role == role


class ZoneState:
    def __init__(self, zone: Zone, grace_s: float = 0.0) -> None:
        self.zone = zone
        self.grace_s = grace_s
        self.started_at: float | None = None
        self.present_since: dict[Role, float | None] = dict.fromkeys(ROLES)
        self.last_seen: dict[Role, float | None] = dict.fromkeys(ROLES)
        self.empty_since: float | None = None
        self.objects_since: dict[str, float] = {}
        self._objects_last_seen: dict[str, float] = {}
        self._tracks: list[TrackObs] = []

    @property
    def occupied_since(self) -> float | None:
        """First moment a guest was present; None while no guest is."""
        return self.present_since["guest"]

    def update(self, frame: Frame) -> None:
        ts = frame.ts
        if self.started_at is None:
            self.started_at = ts
        poly = self.zone.polygon
        self._tracks = [t for t in frame.tracks if point_in_polygon(foot_point(t.bbox), poly)]

        for role in ROLES:
            if any(_has_role(t, role) for t in self._tracks):
                if self.present_since[role] is None:
                    self.present_since[role] = ts
                    if role == "guest":
                        # "Nobody came since they sat down": staff absence starts now.
                        self.last_seen["staff"] = ts
                self.last_seen[role] = ts
            elif self.present_since[role] is not None and self._expired(self.last_seen[role], ts):
                self.present_since[role] = None

        if self.present_since["any"] is not None:
            self.empty_since = None
        elif self.empty_since is None:
            self.empty_since = ts

        labels = {o.label for o in frame.objects if point_in_polygon(box_centre(o.bbox), poly)}
        for label in labels:
            self.objects_since.setdefault(label, ts)
            self._objects_last_seen[label] = ts
        for label in list(self.objects_since):
            if label not in labels and self._expired(self._objects_last_seen[label], ts):
                del self.objects_since[label]
                del self._objects_last_seen[label]

    def _expired(self, last: float | None, now: float) -> bool:
        return last is None or now - last > self.grace_s

    # Queries used by the engine. Durations return None when the fact does not hold.

    def present_for(self, role: Role, now: float) -> float | None:
        since = self.present_since[role]
        return None if since is None else now - since

    def absent_for(self, role: Role, now: float) -> float | None:
        if self.present_since[role] is not None or self.started_at is None:
            return None
        last = self.last_seen[role]
        return now - (self.started_at if last is None else last)

    def count(self, role: Role) -> int:
        return sum(1 for t in self._tracks if _has_role(t, role))

    def raised_hand(self, role: Role) -> bool:
        return any(t.raised_hand and _has_role(t, role) for t in self._tracks)

    def unattended_for(self, labels: list[str], now: float) -> float | None:
        """How long any of `labels` has been in the zone with no person there."""
        if self.empty_since is None:
            return None
        placed = [self.objects_since[label] for label in labels if label in self.objects_since]
        if not placed:
            return None
        return now - max(min(placed), self.empty_since)
