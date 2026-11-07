import itertools
from collections.abc import Mapping
from dataclasses import replace

import pytest
from aivee_contracts.events import StaffSuggestion
from aivee_edge.domain.behaviour import BehaviourFeatures, behaviour_score
from aivee_edge.domain.observation import Frame, TrackObs
from aivee_edge.domain.role import (
    W_APPEARANCE,
    W_BEHAVIOUR,
    W_STANDING,
    RoleClassifier,
    StaffWeights,
    reason_ro,
)

WALKER = BehaviourFeatures(
    duration_s=120,
    speed_per_min=3.0,
    zones_visited=frozenset({"t1", "t2", "t3", "t4"}),
    stationary_ratio=0.3,
    in_staff_zone=False,
)
MIDDLING = BehaviourFeatures(
    duration_s=120,
    speed_per_min=1.25,
    zones_visited=frozenset({"t1", "t2", "t3"}),
    stationary_ratio=0.5,
    in_staff_zone=False,
)
SITTER = BehaviourFeatures(
    duration_s=120,
    speed_per_min=0.0,
    zones_visited=frozenset({"t1"}),
    stationary_ratio=1.0,
    in_staff_zone=False,
)


STANDS_STILL = replace(SITTER, standing_ratio=1.0)
"""A waiter standing at one table: no behaviour signal, but upright the whole window."""
SEATED = replace(SITTER, standing_ratio=0.0)


def test_fixture_scores_cover_the_hysteresis_bands() -> None:
    assert behaviour_score(WALKER) >= 0.7
    assert 0.4 < behaviour_score(MIDDLING) < 0.7
    assert behaviour_score(SITTER) <= 0.4


def _classifier(**kwargs: float) -> RoleClassifier:
    counter = itertools.count(1)
    return RoleClassifier(camera_id="cam1", new_id=lambda: f"s{next(counter)}", **kwargs)


def _frame(*track_ids: int, ts: float = 0.0) -> Frame:
    return Frame(
        ts=ts,
        tracks=tuple(TrackObs(track_id=t, bbox=(0.1, 0.1, 0.2, 0.4)) for t in track_ids),
    )


def _step(
    rc: RoleClassifier,
    features: Mapping[int, BehaviourFeatures],
    appearance: Mapping[int, float | None] | None = None,
) -> tuple[Frame, list[StaffSuggestion]]:
    return rc.assign(_frame(*features), features, appearance or {})


def _track(frame: Frame, track_id: int) -> TrackObs:
    return next(t for t in frame.tracks if t.track_id == track_id)


def test_fusion_without_appearance_uses_behaviour_only() -> None:
    rc = _classifier()
    assert rc.fuse(WALKER, None) == pytest.approx(behaviour_score(WALKER))


def test_default_weights() -> None:
    assert (W_APPEARANCE, W_STANDING, W_BEHAVIOUR) == (0.60, 0.25, 0.15)
    assert StaffWeights() == StaffWeights(appearance=0.60, standing=0.25, behaviour=0.15)


def test_fusion_with_all_signals_is_weighted() -> None:
    rc = _classifier(w_appearance=0.5, w_standing=0.3, w_behaviour=0.2)
    features = replace(MIDDLING, standing_ratio=0.5)
    expected = 0.5 * 0.8 + 0.3 * 0.5 + 0.2 * behaviour_score(MIDDLING)
    assert rc.fuse(features, 0.8) == pytest.approx(expected)


def test_fusion_renormalises_over_the_available_signals() -> None:
    rc = _classifier()
    # Stance unknown: appearance and behaviour only, 0.60 + 0.15 = 0.75 of weight.
    expected = (0.60 * 1.0 + 0.15 * behaviour_score(SITTER)) / 0.75
    assert rc.fuse(SITTER, 1.0) == pytest.approx(expected)


def test_fusion_with_appearance_only() -> None:
    assert _classifier().fuse(None, 0.8) == pytest.approx(0.8)
    assert _classifier().fuse(None, None) == 0.0


def test_zero_weights_never_divide_by_zero() -> None:
    rc = _classifier(w_appearance=0.0, w_standing=0.0, w_behaviour=0.0)
    assert rc.fuse(STANDS_STILL, 1.0) == 0.0


def test_enrolled_staff_standing_still_becomes_staff() -> None:
    rc = _classifier()
    assert rc.fuse(STANDS_STILL, 1.0) == pytest.approx(0.85)
    frame, suggestions = _step(rc, {1: STANDS_STILL}, {1: 1.0})
    assert _track(frame, 1).role == "staff"
    assert suggestions[0].reason_ro == "seamănă cu personalul, stă în picioare"


def test_seated_guest_stays_guest() -> None:
    rc = _classifier()
    assert rc.fuse(SEATED, 0.0) <= 0.4
    frame, suggestions = _step(rc, {1: SEATED}, {1: 0.0})
    assert _track(frame, 1).role == "guest" and suggestions == []


def test_guest_who_stood_up_stays_below_staff() -> None:
    rc = _classifier()
    assert rc.fuse(STANDS_STILL, 0.0) == pytest.approx(0.25)
    # Even walking around a lot, a guest who looks nothing like staff cannot reach 0.7.
    assert rc.fuse(replace(WALKER, standing_ratio=1.0), 0.0) < 0.7
    frame, _ = _step(rc, {1: STANDS_STILL}, {1: 0.0})
    assert _track(frame, 1).role == "guest"


def test_without_appearance_standing_is_ignored() -> None:
    """No profiles enrolled: behaviour alone decides, exactly as before the standing signal."""
    rc = _classifier()
    assert rc.fuse(STANDS_STILL, None) == pytest.approx(behaviour_score(SITTER))
    frame, _ = _step(rc, {1: STANDS_STILL})
    assert _track(frame, 1).role == "guest"
    walker = replace(WALKER, standing_ratio=1.0)
    assert rc.fuse(walker, None) == pytest.approx(behaviour_score(WALKER))


def test_appearance_can_lift_a_middling_walker_to_staff() -> None:
    rc = _classifier()
    frame, _ = _step(rc, {1: MIDDLING}, {1: 1.0})
    assert _track(frame, 1).role == "staff"


def test_assign_sets_role_and_score_and_keeps_other_fields() -> None:
    rc = _classifier()
    src = Frame(
        ts=5.0,
        tracks=(
            TrackObs(track_id=1, bbox=(0.1, 0.1, 0.2, 0.4), raised_hand=True),
            TrackObs(track_id=2, bbox=(0.5, 0.1, 0.6, 0.4)),
        ),
    )
    frame, _ = rc.assign(src, {1: SITTER, 2: WALKER}, {})
    guest, staff = _track(frame, 1), _track(frame, 2)
    assert guest.role == "guest" and guest.raised_hand is True
    assert staff.role == "staff"
    assert staff.staff_score == pytest.approx(behaviour_score(WALKER))
    assert frame.ts == 5.0
    assert src.tracks[1].role == "guest"  # input frame is untouched


def test_track_without_features_stays_guest() -> None:
    rc = _classifier()
    frame, suggestions = rc.assign(_frame(9), {}, {})
    assert _track(frame, 9).role == "guest"
    assert _track(frame, 9).staff_score == 0.0
    assert suggestions == []


def test_hysteresis_prevents_flicker() -> None:
    rc = _classifier()
    frame, _ = _step(rc, {1: WALKER})
    assert _track(frame, 1).role == "staff"
    # Score dips into the band between thresholds: still staff.
    frame, _ = _step(rc, {1: MIDDLING})
    assert _track(frame, 1).role == "staff"
    # Only a clearly guest-like score flips the role back.
    frame, _ = _step(rc, {1: SITTER})
    assert _track(frame, 1).role == "guest"
    # And the middle band keeps it a guest.
    frame, _ = _step(rc, {1: MIDDLING})
    assert _track(frame, 1).role == "guest"


def test_middle_band_starts_as_guest() -> None:
    frame, _ = _step(_classifier(), {1: MIDDLING})
    assert _track(frame, 1).role == "guest"


def test_confirm_makes_track_staff_forever() -> None:
    rc = _classifier()
    rc.confirm(1)
    frame, suggestions = _step(rc, {1: SITTER})
    assert _track(frame, 1).role == "staff"
    assert _track(frame, 1).staff_score == 1.0
    assert suggestions == []


def test_reject_makes_track_guest_and_silences_suggestions() -> None:
    rc = _classifier()
    rc.reject(1)
    frame, suggestions = _step(rc, {1: WALKER})
    assert _track(frame, 1).role == "guest"
    assert _track(frame, 1).staff_score == 0.0
    assert suggestions == []


def test_latest_owner_decision_wins() -> None:
    rc = _classifier()
    rc.reject(1)
    rc.confirm(1)
    frame, _ = _step(rc, {1: SITTER})
    assert _track(frame, 1).role == "staff"


def test_suggestion_is_emitted_once_per_track() -> None:
    rc = _classifier()
    _, first = _step(rc, {1: WALKER, 2: SITTER})
    _, again = _step(rc, {1: WALKER, 2: SITTER})
    _step(rc, {1: SITTER})
    _, after_flip = _step(rc, {1: WALKER})
    assert len(first) == 1
    s = first[0]
    assert s.suggestion_id == "s1"
    assert s.camera_id == "cam1"
    assert s.track_id == 1
    assert s.staff_score == pytest.approx(behaviour_score(WALKER))
    assert "vizitează 4 mese" in s.reason_ro
    assert again == [] and after_flip == []


def test_forget_clears_track_state() -> None:
    rc = _classifier()
    _step(rc, {1: WALKER})
    rc.forget(1)
    rc.forget(1)
    _, suggestions = _step(rc, {1: WALKER})
    assert len(suggestions) == 1


def test_reason_mentions_each_signal() -> None:
    staffish = BehaviourFeatures(
        duration_s=120,
        speed_per_min=3.0,
        zones_visited=frozenset({"t1", "t2", "t3", "t4"}),
        stationary_ratio=0.2,
        in_staff_zone=True,
    )
    assert reason_ro(staffish, 0.9) == (
        "vizitează 4 mese, se mișcă mult, intră în zona personalului, seamănă cu personalul"
    )


def test_reason_uses_romanian_plural_and_fallback() -> None:
    many = BehaviourFeatures(120, 0.0, frozenset(f"t{i}" for i in range(20)), 1.0, False)
    assert reason_ro(many, None) == "vizitează 20 de mese"
    assert reason_ro(SITTER, None) == "se comportă ca personalul"
    assert reason_ro(STANDS_STILL, None) == "se comportă ca personalul"  # stance needs appearance
    assert reason_ro(replace(SITTER, standing_ratio=0.2), 1.0) == "seamănă cu personalul"
    assert reason_ro(None, None) == "se comportă ca personalul"
