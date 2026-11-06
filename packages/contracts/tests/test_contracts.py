import pytest
from aivee_contracts.commands import EdgeCommand
from aivee_contracts.detections import DetectedObject, DetectedTrack, Detections
from aivee_contracts.events import AlertEvent, StaffSuggestion, Verification, before_snapshot_id
from aivee_contracts.geometry import Zone
from aivee_contracts.rules import ANYWHERE_TAG, VISUAL_THRESHOLD, Action, Condition, Rule
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


def test_alert_event_accepts_arrived() -> None:
    ev = AlertEvent.model_validate(
        {
            "event_id": "e1",
            "rule_id": "r1",
            "camera_id": "c",
            "zone_id": "t1",
            "state": "arrived",
            "at": "2026-11-06T12:00:00Z",
            "summary_ro": "Masa 1: a venit un angajat",
        }
    )
    assert ev.state == "arrived"


def test_topics_are_scoped_per_device() -> None:
    t = Topics(site="demo", device="edge-01")
    assert t.events == "aivee/demo/edge-01/events"
    assert t.status == "aivee/demo/edge-01/status"
    assert t.rules == "aivee/demo/edge-01/rules"
    assert t.snapshot("e1") == "aivee/demo/edge-01/snapshots/e1"
    assert Topics.shared_events() == "$share/ingest/aivee/+/+/events"


def test_wildcard_and_shared_topics() -> None:
    assert Topics(site="demo", device="edge-01").config == "aivee/demo/edge-01/config"
    assert Topics.any_device("status") == "aivee/+/+/status"
    assert Topics.shared_suggestions() == "$share/ingest/aivee/+/+/suggestions"


def test_command_and_detections_topics() -> None:
    t = Topics(site="demo", device="edge-01")
    assert t.commands == "aivee/demo/edge-01/commands"
    assert t.detections == "aivee/demo/edge-01/detections"


def test_edge_command_kind_is_constrained() -> None:
    data = {
        "command_id": "c1",
        "kind": "confirm_staff",
        "camera_id": "cam-01",
        "track_id": 7,
        "suggestion_id": "s1",
        "at": "2026-11-06T12:00:00Z",
    }
    cmd = EdgeCommand.model_validate(data)
    assert EdgeCommand.model_validate_json(cmd.model_dump_json()) == cmd
    with pytest.raises(ValidationError):
        EdgeCommand.model_validate({**data, "kind": "delete_everything"})


def test_detections_round_trip_and_boxes_are_normalised() -> None:
    d = Detections.model_validate(
        {
            "camera_id": "cam-01",
            "ts": "2026-11-06T12:00:00Z",
            "tracks": [
                {"track_id": 1, "bbox": [0.1, 0.2, 0.3, 0.9], "role": "staff", "staff_score": 0.8}
            ],
            "objects": [{"label": "cup", "bbox": [0.4, 0.5, 0.45, 0.55]}],
        }
    )
    assert Detections.model_validate_json(d.model_dump_json()) == d
    assert d.tracks[0].raised_hand is False
    with pytest.raises(ValidationError):
        DetectedObject(label="cup", bbox=(0.4, 0.5, 1.2, 0.55))
    with pytest.raises(ValidationError):
        DetectedTrack(track_id=1, bbox=(0, 0, 1, 1), role="waiter", staff_score=0.5)  # type: ignore[arg-type]


def test_staff_suggestion_snapshot_defaults_to_false() -> None:
    s = StaffSuggestion(suggestion_id="s", camera_id="c", track_id=1, staff_score=0.9, reason_ro="")
    assert s.snapshot is False


def test_object_gone_condition_requires_objects() -> None:
    with pytest.raises(ValidationError):
        Condition(kind="object_gone")
    cond = Condition(kind="object_gone", objects=["wine glass"], min_duration_s=30)
    assert cond.objects == ["wine glass"]


def test_alert_event_object_change_is_optional_and_backward_compatible() -> None:
    old = {
        "event_id": "e1",
        "rule_id": "r1",
        "camera_id": "c",
        "zone_id": "t1",
        "state": "opened",
        "at": "2026-11-06T10:00:00Z",
        "summary_ro": "Masa 1",
    }
    assert AlertEvent.model_validate(old).object_change is None
    event = AlertEvent.model_validate(
        {**old, "object_change": {"kind": "gone", "objects": ["wine glass"]}}
    )
    assert event.object_change is not None
    assert event.object_change.before_snapshot is False


def test_verification_defaults() -> None:
    v = Verification(status="pending")
    assert (v.summary_ro, v.object_ro, v.model, v.latency_ms) == ("", None, None, None)
    with pytest.raises(ValidationError):
        Verification.model_validate({"status": "maybe"})


def test_before_snapshot_topic_and_id() -> None:
    t = Topics(site="demo", device="edge-01")
    assert t.snapshot_before("e1") == "aivee/demo/edge-01/snapshots/e1-before"
    assert before_snapshot_id("e1") == "e1-before"


# -- open rules: object_present and visual ------------------------------------------------


def test_object_present_needs_objects_and_never_a_person() -> None:
    with pytest.raises(ValidationError):
        Condition(kind="object_present")
    with pytest.raises(ValidationError):
        Condition(kind="object_present", objects=["person"])
    c = Condition(kind="object_present", objects=["bear"], min_duration_s=2)
    assert c.objects == ["bear"] and c.role == "any"


def test_visual_needs_a_positive_prompt() -> None:
    with pytest.raises(ValidationError):
        Condition(kind="visual", negative=["a normal room"])
    with pytest.raises(ValidationError):
        Condition(kind="visual", positive=["  "])


def test_visual_threshold_is_a_share_and_defaults_from_calibration() -> None:
    c = Condition(kind="visual", positive=["a photo of fire"], negative=["a room"])
    assert c.threshold == VISUAL_THRESHOLD and c.crop is None
    for bad in (-0.1, 1.5):
        with pytest.raises(ValidationError):
            Condition(kind="visual", positive=["fire"], threshold=bad)
    with pytest.raises(ValidationError):
        Condition.model_validate({"kind": "visual", "positive": ["fire"], "crop": "table"})


def test_visual_rule_on_the_whole_frame_round_trips() -> None:
    rule = Rule(
        id="r9",
        camera_id="cam-1",
        name="Foc",
        prompt_ro="dacă e foc",
        zone_tag=ANYWHERE_TAG,
        all_of=[
            Condition(
                kind="visual",
                positive=["a photo of fire", "flames"],
                negative=["a photo of a normal restaurant room"],
                min_duration_s=3,
                threshold=0.6,
                crop="frame",
                label_ro="foc",
            )
        ],
        action=Action(type="telegram"),
        cooldown_s=120,
    )
    assert Rule.model_validate_json(rule.model_dump_json()) == rule


def test_old_rule_payloads_without_the_new_fields_stay_valid() -> None:
    old = {
        "id": "r1",
        "camera_id": "cam-1",
        "name": "Masă nedebarasată",
        "prompt_ro": "masa nedebarasată",
        "zone_tag": "table",
        "all_of": [{"kind": "objects_unattended", "role": "any", "objects": ["cup"]}],
        "action": {"type": "telegram"},
    }
    rule = Rule.model_validate(old)
    assert rule.all_of[0].positive == [] and rule.all_of[0].label_ro == ""
