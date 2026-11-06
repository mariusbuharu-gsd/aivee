import pytest
from aivee_contracts.events import AlertEvent
from aivee_contracts.geometry import Zone
from aivee_contracts.rules import Action, Condition, Rule
from aivee_contracts.topics import Topics
from pydantic import ValidationError


def test_zone_polygon_needs_three_points() -> None:
    with pytest.raises(ValidationError):
        Zone(id="t1", name="Masa 1", tag="table", polygon=[(0.1, 0.1), (0.2, 0.2)])


def test_zone_coordinates_are_normalised() -> None:
    with pytest.raises(ValidationError):
        Zone(id="t1", name="Masa 1", tag="table", polygon=[(0, 0), (1.5, 0), (0, 1)])


def test_unattended_table_rule_round_trips() -> None:
    rule = Rule(
        id="r1",
        camera_id="cam-1",
        name="Masă neservită",
        prompt_ro="Anunță ospătarul dacă la o masă nu a venit nimeni de 10 minute",
        zone_tag="table",
        all_of=[
            Condition(kind="present", role="guest", min_duration_s=60),
            Condition(kind="absent", role="staff", min_duration_s=600),
        ],
        action=Action(type="telegram"),
        cooldown_s=300,
    )
    assert Rule.model_validate_json(rule.model_dump_json()) == rule


def test_rule_needs_at_least_one_condition() -> None:
    with pytest.raises(ValidationError):
        Rule(
            id="r1",
            camera_id="c",
            name="n",
            prompt_ro="p",
            zone_tag="table",
            all_of=[],
            action=Action(type="telegram"),
        )


def test_pose_condition_requires_pose() -> None:
    with pytest.raises(ValidationError):
        Condition(kind="pose", role="guest")


def test_objects_condition_requires_objects() -> None:
    with pytest.raises(ValidationError):
        Condition(kind="objects_unattended")


def test_alert_event_state_is_constrained() -> None:
    with pytest.raises(ValidationError):
        AlertEvent.model_validate(
            {
                "event_id": "e1",
                "rule_id": "r1",
                "camera_id": "c",
                "zone_id": "t1",
                "state": "maybe",
                "at": "2026-11-06T12:00:00Z",
                "summary_ro": "x",
            }
        )


def test_topics_are_scoped_per_device() -> None:
    t = Topics(site="demo", device="edge-01")
    assert t.events == "aivee/demo/edge-01/events"
    assert t.status == "aivee/demo/edge-01/status"
    assert t.rules == "aivee/demo/edge-01/rules"
    assert t.snapshot("e1") == "aivee/demo/edge-01/snapshots/e1"
    assert Topics.shared_events() == "$share/ingest/aivee/+/+/events"
