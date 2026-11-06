"""Guest or staff? Fuses behaviour and appearance into a stable role per track.

`staff_score = w_b·behaviour + w_a·appearance` (behaviour only when there is no
appearance score). Hysteresis keeps roles from flickering: a track becomes staff at
>= 0.7 and turns back into a guest only at <= 0.4. The owner has the last word:
`confirm` / `reject` override the score for that track. The first time a track
becomes staff on its own, a `StaffSuggestion` asks the owner to confirm.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from aivee_contracts.events import StaffSuggestion

from aivee_edge.domain.behaviour import BehaviourFeatures, behaviour_score
from aivee_edge.domain.observation import Frame, PersonRole

W_BEHAVIOUR = 0.5
W_APPEARANCE = 0.5
"""Equal weights: neither a uniform-like outfit nor walking around alone makes staff."""
BECOME_STAFF = 0.7
BECOME_GUEST = 0.4

FALLBACK_REASON = "se comportă ca personalul"


@dataclass
class _TrackState:
    role: PersonRole = "guest"
    decision: PersonRole | None = None  # owner's confirm/reject
    suggested: bool = False


def _mese(n: int) -> str:
    # Romanian inserts "de" for 20+ (except when the last two digits are 01-19).
    return f"{n} de mese" if n >= 20 and not 1 <= n % 100 <= 19 else f"{n} mese"


def reason_ro(features: BehaviourFeatures | None, appearance: float | None) -> str:
    """Short Romanian explanation for the owner, e.g. "vizitează 4 mese, se mișcă mult"."""
    parts: list[str] = []
    if features is not None:
        tables = len(features.zones_visited)
        if tables >= 2:
            parts.append(f"vizitează {_mese(tables)}")
        if features.speed_per_min >= 1.0 or features.stationary_ratio < 0.5:
            parts.append("se mișcă mult")
        if features.in_staff_zone:
            parts.append("intră în zona personalului")
    if appearance is not None and appearance >= 0.5:
        parts.append("seamănă cu personalul")
    return ", ".join(parts) or FALLBACK_REASON


class RoleClassifier:
    """Per-track role state for one camera. Call `forget` when a track disappears."""

    def __init__(
        self,
        camera_id: str,
        new_id: Callable[[], str],
        *,
        w_behaviour: float = W_BEHAVIOUR,
        w_appearance: float = W_APPEARANCE,
        become_staff: float = BECOME_STAFF,
        become_guest: float = BECOME_GUEST,
    ) -> None:
        self._camera_id = camera_id
        self._new_id = new_id
        self._w_b = w_behaviour
        self._w_a = w_appearance
        self._become_staff = become_staff
        self._become_guest = become_guest
        self._tracks: dict[int, _TrackState] = {}

    def fuse(self, features: BehaviourFeatures | None, appearance: float | None) -> float:
        """staff_score in [0, 1] from whichever signals are available."""
        if features is None:
            return appearance if appearance is not None else 0.0
        behaviour = behaviour_score(features)
        if appearance is None:
            return behaviour
        return (self._w_b * behaviour + self._w_a * appearance) / (self._w_b + self._w_a)

    def confirm(self, track_id: int) -> None:
        self._state(track_id).decision = "staff"

    def reject(self, track_id: int) -> None:
        self._state(track_id).decision = "guest"

    def forget(self, track_id: int) -> None:
        self._tracks.pop(track_id, None)

    def _state(self, track_id: int) -> _TrackState:
        return self._tracks.setdefault(track_id, _TrackState())

    def assign(
        self,
        frame: Frame,
        features_by_track: Mapping[int, BehaviourFeatures],
        appearance_by_track: Mapping[int, float | None],
    ) -> tuple[Frame, list[StaffSuggestion]]:
        """Return a copy of `frame` with role/staff_score set, plus new suggestions."""
        suggestions: list[StaffSuggestion] = []
        tracks = []
        for track in frame.tracks:
            state = self._state(track.track_id)
            features = features_by_track.get(track.track_id)
            appearance = appearance_by_track.get(track.track_id)
            score = self.fuse(features, appearance)

            if state.decision is not None:
                state.role = state.decision
                score = 1.0 if state.decision == "staff" else 0.0
            elif score >= self._become_staff:
                state.role = "staff"
                if not state.suggested:
                    state.suggested = True
                    suggestions.append(
                        StaffSuggestion(
                            suggestion_id=self._new_id(),
                            camera_id=self._camera_id,
                            track_id=track.track_id,
                            staff_score=score,
                            reason_ro=reason_ro(features, appearance),
                        )
                    )
            elif score <= self._become_guest:
                state.role = "guest"

            tracks.append(replace(track, role=state.role, staff_score=score))
        return replace(frame, tracks=tuple(tracks)), suggestions
