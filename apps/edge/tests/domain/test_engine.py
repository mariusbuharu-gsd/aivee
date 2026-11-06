from collections.abc import Iterator
from datetime import UTC, datetime
from itertools import count

from aivee_contracts.events import AlertEvent
from aivee_contracts.geometry import Zone
from aivee_contracts.rules import Action, Condition, Rule
from aivee_edge.domain.engine import SituationEngine
from aivee_edge.domain.observation import BBox, Frame, ObjectObs, PersonRole, TrackObs

CAM = "cam1"


def square(x: float, y: float, size: float = 0.2) -> list[tuple[float, float]]:
    return [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]


def at(zone: Zone) -> BBox:
    """A box whose foot point is inside `zone` (zones are squares built by `square`)."""
    (x, y), (x2, _), _, (_, y2) = zone.polygon
    cx, cy = (x + x2) / 2, (y + y2) / 2
    return (cx - 0.02, cy - 0.05, cx + 0.02, cy)


TABLE1 = Zone(id="t1", name="Masa 1", tag="table", polygon=square(0.0, 0.0))
TABLE2 = Zone(id="t2", name="Masa 2", tag="table", polygon=square(0.5, 0.0))
ENTRANCE = Zone(id="e1", name="Intrare", tag="entrance", polygon=square(0.0, 0.6))


def rule(
    rule_id: str, tag: str, *conds: Condition, cooldown_s: int = 0, enabled: bool = True
) -> Rule:
    return Rule(
        id=rule_id,
        camera_id=CAM,
        name=rule_id,
        prompt_ro="...",
        zone_tag=tag,
        all_of=list(conds),
        action=Action(type="telegram"),
        cooldown_s=cooldown_s,
        enabled=enabled,
    )


UNATTENDED = rule(
    "unattended",
    "table",
    Condition(kind="present", role="guest", min_duration_s=60),
    Condition(kind="absent", role="staff", min_duration_s=600),
)
CALLS = rule("calls", "table", Condition(kind="pose", role="guest", pose="raised_hand"))
QUEUE = rule("queue", "entrance", Condition(kind="count", role="any", min_count=4))
UNCLEARED = rule(
    "uncleared",
    "table",
    Condition(kind="objects_unattended", objects=["cup", "bowl"], min_duration_s=300),
)


def guest(zone: Zone, track_id: int = 1, hand: bool = False) -> TrackObs:
    return TrackObs(track_id=track_id, bbox=at(zone), raised_hand=hand)


def staff(zone: Zone, track_id: int = 99) -> TrackObs:
    role: PersonRole = "staff"
    return TrackObs(track_id=track_id, bbox=at(zone), role=role)


def cup(zone: Zone) -> ObjectObs:
    return ObjectObs("cup", at(zone))


def engine(*rules: Rule, zones: tuple[Zone, ...] = (TABLE1, TABLE2, ENTRANCE)) -> SituationEngine:
    ids: Iterator[int] = count(1)
    return SituationEngine(
        list(rules), list(zones), id_factory=lambda: f"ev{next(ids)}", camera_id=CAM
    )


def play(eng: SituationEngine, frames: list[Frame]) -> list[AlertEvent]:
    return [ev for f in frames for ev in eng.step(f)]


def seated(zone: Zone, start: int, end: int, step: int = 10) -> list[Frame]:
    return [Frame(ts=t, tracks=(guest(zone),)) for t in range(start, end + 1, step)]


def test_unattended_table_opens_after_threshold() -> None:
    eng = engine(UNATTENDED)
    assert play(eng, seated(TABLE1, 0, 590)) == []
    events = eng.step(Frame(ts=600, tracks=(guest(TABLE1),)))
    assert len(events) == 1
    ev = events[0]
    assert (ev.event_id, ev.rule_id, ev.zone_id, ev.camera_id) == ("ev1", "unattended", "t1", CAM)
    assert ev.state == "opened"
    assert ev.at == datetime.fromtimestamp(600, tz=UTC)
    assert ev.summary_ro == "Masa 1: neservită de 10 min"
    # Stays open without repeating.
    assert play(eng, seated(TABLE1, 610, 700)) == []


def test_unattended_table_closes_when_staff_arrives() -> None:
    eng = engine(UNATTENDED)
    play(eng, seated(TABLE1, 0, 600))
    events = eng.step(Frame(ts=620, tracks=(guest(TABLE1), staff(TABLE1))))
    assert [(e.state, e.rule_id, e.zone_id, e.event_id) for e in events] == [
        ("closed", "unattended", "t1", "ev2")
    ]
    assert events[0].summary_ro == "Masa 1: rezolvat"


def test_raised_hand_opens_immediately() -> None:
    eng = engine(CALLS)
    events = eng.step(Frame(ts=5, tracks=(guest(TABLE2, hand=True),)))
    assert [(e.state, e.zone_id, e.summary_ro) for e in events] == [
        ("opened", "t2", "Masa 2: un client cheamă")
    ]
    assert [e.state for e in eng.step(Frame(ts=6, tracks=(guest(TABLE2),)))] == ["closed"]


def test_queue_opens_at_min_count() -> None:
    eng = engine(QUEUE)
    three = tuple(guest(ENTRANCE, i) for i in range(3))
    assert eng.step(Frame(ts=0, tracks=three)) == []
    events = eng.step(Frame(ts=1, tracks=(*three, staff(ENTRANCE))))
    assert [(e.state, e.zone_id, e.summary_ro) for e in events] == [
        ("opened", "e1", "Intrare: 4 persoane așteaptă")
    ]


def test_uncleared_table_needs_objects_and_no_people() -> None:
    eng = engine(UNCLEARED)
    # Guests eat for a while: objects with people are fine.
    with_people = [Frame(ts=t, tracks=(guest(TABLE1),), objects=(cup(TABLE1),)) for t in (0, 400)]
    assert play(eng, with_people) == []
    # They leave at 410; the cup stays.
    left = [Frame(ts=t, objects=(cup(TABLE1),)) for t in range(410, 701, 10)]
    assert play(eng, left) == []
    events = eng.step(Frame(ts=710, objects=(cup(TABLE1),)))
    assert [(e.state, e.zone_id, e.summary_ro) for e in events] == [
        ("opened", "t1", "Masa 1: nedebarasată de 5 min")
    ]
    # The cup is cleared: the alert closes, and an empty bare table never opens one.
    assert [e.state for e in eng.step(Frame(ts=720))] == ["closed"]
    assert play(eng, [Frame(ts=t) for t in range(730, 1500, 10)]) == []


def test_cooldown_blocks_reopen() -> None:
    eng = engine(rule("calls", "table", *CALLS.all_of, cooldown_s=60))
    hand = Frame(ts=0, tracks=(guest(TABLE1, hand=True),))
    down = Frame(ts=1, tracks=(guest(TABLE1),))
    assert [e.state for e in play(eng, [hand, down])] == ["opened", "closed"]
    assert eng.step(Frame(ts=30, tracks=(guest(TABLE1, hand=True),))) == []
    assert eng.step(Frame(ts=31, tracks=(guest(TABLE1),))) == []
    reopened = eng.step(Frame(ts=60, tracks=(guest(TABLE1, hand=True),)))
    assert [e.state for e in reopened] == ["opened"]


def test_rule_applies_to_every_zone_with_tag() -> None:
    eng = engine(UNATTENDED)
    frames = [
        Frame(ts=t, tracks=(guest(TABLE1, 1), guest(TABLE2, 2), guest(ENTRANCE, 3)))
        for t in range(0, 601, 10)
    ]
    events = play(eng, frames)
    assert sorted((e.zone_id, e.state) for e in events) == [("t1", "opened"), ("t2", "opened")]
    # Staff serves table 2 only: table 1 stays open.
    events = eng.step(Frame(ts=610, tracks=(guest(TABLE1, 1), guest(TABLE2, 2), staff(TABLE2))))
    assert [(e.zone_id, e.state) for e in events] == [("t2", "closed")]


def test_disabled_rule_is_ignored() -> None:
    eng = engine(rule("calls", "table", *CALLS.all_of, enabled=False))
    assert eng.step(Frame(ts=0, tracks=(guest(TABLE1, hand=True),))) == []


def test_rule_for_another_camera_is_ignored() -> None:
    other = CALLS.model_copy(update={"camera_id": "cam2"})
    eng = engine(other)
    assert eng.step(Frame(ts=0, tracks=(guest(TABLE1, hand=True),))) == []


def test_update_rules_takes_effect() -> None:
    eng = engine()
    hand = Frame(ts=0, tracks=(guest(TABLE1, hand=True),))
    assert eng.step(hand) == []
    eng.update_rules([CALLS])
    assert [e.state for e in eng.step(Frame(ts=1, tracks=hand.tracks))] == ["opened"]


def test_removing_a_rule_closes_its_open_alerts() -> None:
    eng = engine(CALLS)
    eng.step(Frame(ts=0, tracks=(guest(TABLE1, hand=True),)))
    eng.update_rules([])
    events = eng.step(Frame(ts=1, tracks=(guest(TABLE1, hand=True),)))
    assert [(e.state, e.rule_id, e.zone_id) for e in events] == [("closed", "calls", "t1")]


def test_present_only_rule_summary() -> None:
    eng = engine(
        rule("seated", "table", Condition(kind="present", role="guest", min_duration_s=30))
    )
    events = play(eng, seated(TABLE1, 0, 30))
    assert [e.summary_ro for e in events] == ["Masa 1: ocupată de 30 s"]


def test_injected_clock_converts_frame_time() -> None:
    base = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    eng = SituationEngine(
        [CALLS],
        [TABLE1],
        id_factory=lambda: "x",
        camera_id=CAM,
        to_datetime=lambda ts: base.replace(second=int(ts)),
    )
    [ev] = eng.step(Frame(ts=7, tracks=(guest(TABLE1, hand=True),)))
    assert ev.at == base.replace(second=7)


def test_update_zones_keeps_state_of_unchanged_zones() -> None:
    eng = engine(UNATTENDED, zones=(TABLE1,))
    play(eng, seated(TABLE1, 0, 590))
    eng.update_zones([TABLE1, TABLE2])
    events = eng.step(Frame(ts=600, tracks=(guest(TABLE1),)))
    assert [(e.state, e.zone_id) for e in events] == [("opened", "t1")]


def test_update_zones_adds_new_zones() -> None:
    eng = engine(CALLS, zones=(TABLE1,))
    eng.update_zones([TABLE1, TABLE2])
    events = eng.step(Frame(ts=0, tracks=(guest(TABLE2, hand=True),)))
    assert [(e.state, e.zone_id) for e in events] == [("opened", "t2")]


def test_removing_a_zone_closes_its_open_alerts() -> None:
    eng = engine(CALLS, zones=(TABLE1, TABLE2))
    eng.step(Frame(ts=0, tracks=(guest(TABLE1, hand=True),)))
    eng.update_zones([TABLE2])
    events = eng.step(Frame(ts=1, tracks=(guest(TABLE1, hand=True),)))
    assert [(e.state, e.zone_id, e.summary_ro) for e in events] == [
        ("closed", "t1", "Masa 1: rezolvat")
    ]


def test_moved_zone_restarts_its_timers() -> None:
    eng = engine(UNATTENDED, zones=(TABLE1,))
    play(eng, seated(TABLE1, 0, 590))
    moved = TABLE1.model_copy(update={"polygon": square(0.0, 0.0, size=0.3)})
    eng.update_zones([moved])
    assert eng.step(Frame(ts=600, tracks=(guest(moved),))) == []
