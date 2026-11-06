"""Guest or staff? Fuses appearance, stance and behaviour into a stable role per track.

    staff_score = (w_a·appearance + w_s·standing + w_b·behaviour) / (sum of the weights used)

with defaults w_a = 0.60, w_s = 0.25, w_b = 0.15, normalised over the signals that are
available (standing is unknown until stance has been seen; behaviour needs a track).
Standing only counts next to appearance: with no appearance score (no profiles enrolled,
or not embedded yet) the score is behaviour alone, as before the standing signal, so a
standing person is never staff just for standing. A guest who stands up but looks
nothing like staff tops out at w_s + w_b = 0.40 < 0.7.

Hysteresis keeps roles from flickering: a track becomes staff at >= 0.7 and turns back
into a guest only at <= 0.4. The owner has the last word:
`confirm` / `reject` override the score for that track. The first time a track
becomes staff on its own, a `StaffSuggestion` asks the owner to confirm.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from aivee_contracts.events import StaffSuggestion

from aivee_edge.domain.behaviour import BehaviourFeatures, behaviour_score
from aivee_edge.domain.observation import Frame, PersonRole

W_APPEARANCE = 0.60
"""Appearance vs enrolled staff photos: the strongest signal once calibrated."""
W_STANDING = 0.25
"""Share of the last few seconds spent standing: staff stand, guests sit."""
W_BEHAVIOUR = 0.15
"""Walking between tables; a waiter standing at one table scores ~0 here."""
BECOME_STAFF = 0.7
BECOME_GUEST = 0.4

FALLBACK_REASON = "se comportă ca personalul"
STANDING_REASON = 0.3
"""Standing ratio from which the reason mentions "stă în picioare". Low on purpose: with
appearance 1 a track crosses 0.7 at a standing ratio of 0.4, while its window still fills."""


@dataclass(frozen=True)
class StaffWeights:
    """Fusion weights (env `STAFF_W_APPEARANCE`, `STAFF_W_STANDING`, `STAFF_W_BEHAVIOUR`)."""

    appearance: float = W_APPEARANCE
    standing: float = W_STANDING
    behaviour: float = W_BEHAVIOUR


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
    standing = features.standing_ratio if features is not None else None
    if appearance is not None and standing is not None and standing >= STANDING_REASON:
        parts.append("stă în picioare")
    return ", ".join(parts) or FALLBACK_REASON


class RoleClassifier:
    """Per-track role state for one camera. Call `forget` when a track disappears."""

    def __init__(
        self,
        camera_id: str,
        new_id: Callable[[], str],
        *,
        w_appearance: float = W_APPEARANCE,
        w_standing: float = W_STANDING,
        w_behaviour: float = W_BEHAVIOUR,
        become_staff: float = BECOME_STAFF,
        become_guest: float = BECOME_GUEST,
    ) -> None:
        self._camera_id = camera_id
        self._new_id = new_id
        self._w_a = w_appearance
        self._w_s = w_standing
        self._w_b = w_behaviour
        self._become_staff = become_staff
        self._become_guest = become_guest
        self._tracks: dict[int, _TrackState] = {}

    def fuse(self, features: BehaviourFeatures | None, appearance: float | None) -> float:
        """staff_score in [0, 1] from whichever signals are available."""
        behaviour = behaviour_score(features) if features is not None else None
        if appearance is None:
            return behaviour if behaviour is not None else 0.0
        standing = features.standing_ratio if features is not None else None
        terms = [
            (w, v)
            for w, v in (
                (self._w_a, appearance),
                (self._w_s, standing),
                (self._w_b, behaviour),
            )
            if v is not None
        ]
        total = sum(w for w, _ in terms)
        return sum(w * v for w, v in terms) / total if total > 0 else 0.0

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
