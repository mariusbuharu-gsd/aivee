import pytest
from aivee_contracts.geometry import Zone
from aivee_edge.domain.observation import BBox, Frame, ObjectObs, PersonRole, TrackObs
from aivee_edge.domain.zone_state import ZoneState

TABLE = Zone(
    id="t1", name="Masa 1", tag="table", polygon=[(0.0, 0.0), (0.5, 0.0), (0.5, 0.5), (0.0, 0.5)]
)
IN: BBox = (0.1, 0.1, 0.3, 0.4)  # foot point (0.2, 0.4): inside
OUT: BBox = (0.6, 0.6, 0.8, 0.9)  # foot point (0.7, 0.9): outside
CUP_IN: BBox = (0.2, 0.2, 0.25, 0.25)


def person(
    track_id: int, role: PersonRole = "guest", bbox: BBox = IN, hand: bool = False
) -> TrackObs:
    return TrackObs(track_id=track_id, bbox=bbox, role=role, raised_hand=hand)


def frame(ts: float, *tracks: TrackObs, objects: tuple[ObjectObs, ...] = ()) -> Frame:
    return Frame(ts=ts, tracks=tracks, objects=objects)


def run(state: ZoneState, *frames: Frame) -> ZoneState:
    for f in frames:
        state.update(f)
    return state


def test_present_duration_grows_while_guest_stays() -> None:
    state = run(ZoneState(TABLE), frame(0), frame(10, person(1)), frame(40, person(1)))
    assert state.occupied_since == 10
    assert state.present_for("guest", 40) == 30
    assert state.present_for("any", 40) == 30
    assert state.present_for("staff", 40) is None


def test_person_outside_polygon_is_ignored() -> None:
    state = run(ZoneState(TABLE), frame(0, person(1, bbox=OUT)))
    assert state.count("any") == 0
    assert state.present_for("guest", 0) is None


def test_staff_absence_counts_from_when_guests_sat_down() -> None:
    state = run(
        ZoneState(TABLE),
        frame(0, person(9, "staff")),  # a waiter passes, long before
        frame(5),
        frame(100, person(1)),  # guests sit down
        frame(160, person(1)),
    )
    assert state.last_seen["staff"] == 100
    assert state.absent_for("staff", 160) == 60


def test_staff_visit_resets_absence() -> None:
    state = run(
        ZoneState(TABLE),
        frame(0, person(1)),
        frame(50, person(1), person(9, "staff")),
        frame(80, person(1)),
    )
    assert state.absent_for("staff", 80) == 30
    assert state.absent_for("guest", 80) is None


def test_absence_before_anyone_is_seen_counts_from_first_frame() -> None:
    state = ZoneState(TABLE)
    assert state.absent_for("any", 0) is None
    run(state, frame(3), frame(13))
    assert state.absent_for("any", 13) == 10
    assert state.empty_since == 3


def test_zone_empty_resets_occupancy() -> None:
    state = run(ZoneState(TABLE), frame(0, person(1)), frame(30, person(1)), frame(31))
    assert state.occupied_since is None
    assert state.empty_since == 31
    assert state.present_for("guest", 31) is None
    run(state, frame(40, person(2)))
    assert state.occupied_since == 40
    assert state.empty_since is None
    assert state.present_for("guest", 45) == 5


def test_count_and_raised_hand_by_role() -> None:
    state = run(
        ZoneState(TABLE),
        frame(0, person(1), person(2, hand=True), person(9, "staff"), person(3, bbox=OUT)),
    )
    assert state.count("guest") == 2
    assert state.count("staff") == 1
    assert state.count("any") == 3
    assert state.raised_hand("guest")
    assert state.raised_hand("any")
    assert not state.raised_hand("staff")


def test_objects_without_people_tracks_duration() -> None:
    cup = ObjectObs("cup", CUP_IN)
    state = run(
        ZoneState(TABLE),
        frame(0, person(1), objects=(cup,)),
        frame(60, objects=(cup,)),  # guests left, the cup stays
        frame(90, objects=(cup,)),
    )
    assert state.objects_since == {"cup": 0}
    assert state.unattended_for(["cup", "bowl"], 90) == 30
    assert state.unattended_for(["bowl"], 90) is None


def test_objects_with_people_are_not_unattended() -> None:
    cup = ObjectObs("cup", CUP_IN)
    state = run(ZoneState(TABLE), frame(0, person(1), objects=(cup,)))
    assert state.unattended_for(["cup"], 0) is None


def test_objects_placed_after_zone_emptied_count_from_placement() -> None:
    cup = ObjectObs("cup", CUP_IN)
    state = run(ZoneState(TABLE), frame(0), frame(20, objects=(cup,)), frame(50, objects=(cup,)))
    assert state.unattended_for(["cup"], 50) == 30


def test_objects_outside_zone_or_removed_are_forgotten() -> None:
    cup = ObjectObs("cup", CUP_IN)
    far_cup = ObjectObs("cup", OUT)
    state = run(ZoneState(TABLE), frame(0, objects=(cup,)), frame(10, objects=(far_cup,)))
    assert state.objects_since == {}
    assert state.unattended_for(["cup"], 10) is None


@pytest.mark.parametrize("gap", [0.5, 1.0])
def test_grace_bridges_short_detection_gaps(gap: float) -> None:
    state = run(
        ZoneState(TABLE, grace_s=1.0),
        frame(0, person(1)),
        frame(gap),  # the detector missed the guest for one frame
        frame(gap + 0.5, person(1)),
    )
    assert state.occupied_since == 0


def test_grace_expires_on_long_gaps() -> None:
    state = run(ZoneState(TABLE, grace_s=1.0), frame(0, person(1)), frame(5), frame(6, person(1)))
    assert state.occupied_since == 6
