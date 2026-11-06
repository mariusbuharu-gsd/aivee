"""Per-zone presence, absence and objects over time.

A person is in a zone when their foot point is inside its polygon; an object when
its box centre is (for `objects_unattended`). For `object_gone` an object counts by its
base, the bottom-centre of its box: like a person's feet on the floor, a glass's base
sits on the table surface the zone is drawn on, while the centre of a tall bottle seen
from an angle can fall outside it. Durations are measured on `Frame.ts` (seconds). A role or object
missing for at most `grace_s` still counts as present, so a detector that drops a
person for a frame does not reset their timers.

A capture gap (no frames at all, e.g. the stream reconnecting) is not absence: the
engine calls `shift` with the gap, which moves every stored time forward so timers
freeze during the gap and the grace window starts again from the first frame after it.

With `arrive_s > 0` a staff member counts as present only once their foot point has
stayed in the zone for `arrive_s`: a waiter walking past a table has not served it.

`object_present` counts an object by its base, like `object_gone` (a bear stands on the
floor, a knife lies on the table), with the same grace. The whole-frame pseudo-zone
(tag `anywhere`) holds every person and object in the image, edges included.
"""

from aivee_contracts.geometry import Point, Zone
from aivee_contracts.rules import ANYWHERE_TAG, Role

from aivee_edge.domain.geometry import box_centre, foot_point, point_in_polygon
from aivee_edge.domain.objects import Gone, ObjectPresence
from aivee_edge.domain.observation import Frame, TrackObs

ROLES: tuple[Role, ...] = ("guest", "staff", "any")


def _has_role(track: TrackObs, role: Role) -> bool:
    return role == "any" or track.role == role


class ZoneState:
    def __init__(self, zone: Zone, grace_s: float = 0.0, arrive_s: float = 0.0) -> None:
        self.zone = zone
        self.grace_s = grace_s
        self.arrive_s = arrive_s
        self.started_at: float | None = None
        self.present_since: dict[Role, float | None] = dict.fromkeys(ROLES)
        self.last_seen: dict[Role, float | None] = dict.fromkeys(ROLES)
        self.empty_since: float | None = None
        self.objects_since: dict[str, float] = {}
        self._objects_last_seen: dict[str, float] = {}
        self._tracks: list[TrackObs] = []
        self._staff_since: dict[int, float] = {}
        self._staff_last_seen: dict[int, float] = {}
        self.objects = ObjectPresence()
        self._present_objects_since: dict[str, float] = {}
        self._present_objects_last: dict[str, float] = {}
        self._whole_frame = zone.tag == ANYWHERE_TAG

    def _inside(self, p: Point) -> bool:
        return self._whole_frame or point_in_polygon(p, self.zone.polygon)

    @property
    def occupied_since(self) -> float | None:
        """First moment a guest was present; None while no guest is."""
        return self.present_since["guest"]

    def update(self, frame: Frame) -> None:
        ts = frame.ts
        if self.started_at is None:
            self.started_at = ts
        inside = self._inside
        self._tracks = [t for t in frame.tracks if inside(foot_point(t.bbox))]
        settled = self._update_staff(ts)

        for role in ROLES:
            here = settled if role == "staff" else any(_has_role(t, role) for t in self._tracks)
            if here:
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

        counts: dict[str, int] = {}
        for o in frame.objects:
            if inside(foot_point(o.bbox)):
                counts[o.label] = counts.get(o.label, 0) + 1
        self.objects.update(ts, counts)
        for label in counts:
            self._present_objects_since.setdefault(label, ts)
            self._present_objects_last[label] = ts
        for label in list(self._present_objects_since):
            if label not in counts and self._expired(self._present_objects_last[label], ts):
                del self._present_objects_since[label]
                del self._present_objects_last[label]

        labels = {o.label for o in frame.objects if inside(box_centre(o.bbox))}
        for label in labels:
            self.objects_since.setdefault(label, ts)
            self._objects_last_seen[label] = ts
        for label in list(self.objects_since):
            if label not in labels and self._expired(self._objects_last_seen[label], ts):
                del self.objects_since[label]
                del self._objects_last_seen[label]

    def shift(self, dt: float) -> None:
        """Move every stored timestamp forward by `dt`, as if the gap had not happened."""

        def moved(t: float | None) -> float | None:
            return None if t is None else t + dt

        self.started_at = moved(self.started_at)
        self.empty_since = moved(self.empty_since)
        for times in (self.present_since, self.last_seen):
            for role in times:
                times[role] = moved(times[role])
        for labels in (
            self.objects_since,
            self._objects_last_seen,
            self._present_objects_since,
            self._present_objects_last,
        ):
            for label in labels:
                labels[label] += dt
        for tracks in (self._staff_since, self._staff_last_seen):
            for tid in tracks:
                tracks[tid] += dt
        self.objects.shift(dt)

    def _update_staff(self, ts: float) -> bool:
        """Track how long each staff member has stood in the zone; True when one of those
        seen in this frame has stayed at least `arrive_s`."""
        here = {t.track_id for t in self._tracks if t.role == "staff"}
        for tid in here:
            self._staff_since.setdefault(tid, ts)
            self._staff_last_seen[tid] = ts
        for tid in list(self._staff_since):
            if tid not in here and self._expired(self._staff_last_seen[tid], ts):
                del self._staff_since[tid]
                del self._staff_last_seen[tid]
        return any(ts - self._staff_since[tid] >= self.arrive_s for tid in here)

    def staff_since(self) -> float | None:
        """Since when the longest-staying staff member still here has been in the zone."""
        return min(self._staff_since.values(), default=None)

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

    def object_present(self, labels: list[str], now: float) -> tuple[str, float] | None:
        """The longest-present of `labels` in the zone and for how long; None if none is."""
        here = [
            (label, now - self._present_objects_since[label])
            for label in labels
            if label in self._present_objects_since
        ]
        return max(here, key=lambda h: h[1], default=None)

    def gone(self, labels: list[str], min_present_s: float, now: float) -> Gone | None:
        """A still-holding disappearance of one of `labels` (see `ObjectPresence`)."""
        return self.objects.gone(labels, min_present_s, now)
