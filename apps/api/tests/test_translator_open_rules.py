"""Open rules (object_present, visual): recorded model outputs through the API's draft checks.

`fixtures/recorded_drafts.json` holds real translator outputs from the nl_to_rule eval
(evals/nl_to_rule/drafts.json, 2026-11-06), so the parse and checks are tested on what
the model actually writes.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from aivee_api.rules.prompt import COCO_CLASSES, INSTRUCTIONS
from aivee_api.rules.service import SMALL_FLAME, clean_visual, draft_to_rule
from aivee_api.rules.translator import RuleDraft, TranslationError
from aivee_contracts.geometry import Zone
from aivee_contracts.rules import ANYWHERE_TAG, Condition

RECORDED: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "recorded_drafts.json").read_text()
)
ZONES = [
    Zone(id="t1", name="Masa 1", tag="table", polygon=[(0.05, 0.5), (0.3, 0.5), (0.3, 0.8)]),
    Zone(id="e1", name="Intrare", tag="entrance", polygon=[(0.75, 0.1), (0.95, 0.1), (0.95, 0.4)]),
]


def recorded(case: str) -> RuleDraft:
    return RuleDraft.model_validate_json(json.dumps(RECORDED[case]))


@pytest.mark.parametrize(("case", "label"), [("present-bear", "bear"), ("present-knife", "knife")])
def test_recorded_object_present_drafts_become_whole_frame_rules(case: str, label: str) -> None:
    rule = draft_to_rule(recorded(case), "cam1", "x", ZONES)
    (c,) = rule.all_of
    assert (rule.zone_tag, c.kind, c.objects, rule.cooldown_s) == (
        ANYWHERE_TAG,
        "object_present",
        [label],
        120,
    )
    assert c.min_duration_s == 2 and c.label_ro


@pytest.mark.parametrize("case", ["visual-fire", "visual-water", "visual-door"])
def test_recorded_visual_drafts_carry_prompts_and_defaults(case: str) -> None:
    rule = draft_to_rule(recorded(case), "cam1", "x", ZONES)
    (c,) = rule.all_of
    assert c.kind == "visual" and rule.zone_tag == ANYWHERE_TAG
    assert c.positive and len(c.negative) >= 3
    assert {"a photo of a room", "a blurry photo"} <= set(c.negative)
    # The recorded output had person prompts in `negative`; the draft check drops them.
    raw = recorded(case).all_of[0].negative
    assert "a photo of a person" in raw
    assert not [n for n in c.negative if "person" in n or "people" in n]
    assert not set(c.positive) & set(c.negative)
    assert (c.min_duration_s, c.threshold, c.crop, rule.cooldown_s) == (3, 0.5, "frame", 120)
    assert c.label_ro and "verificat" in recorded(case).explanation_ro


@pytest.mark.parametrize("case", ["refuse-face", "refuse-age-gender"])
def test_recorded_refusals_stay_refusals(case: str) -> None:
    with pytest.raises(TranslationError) as e:
        draft_to_rule(recorded(case), "cam1", "x", ZONES)
    assert e.value.code == "clarify" and e.value.message_ro


def test_old_kind_recorded_draft_is_unchanged() -> None:
    rule = draft_to_rule(recorded("gone-glass"), "cam1", "x", ZONES)
    assert rule.zone_tag == "table" and rule.all_of[0].kind == "object_gone"


def _draft(zone_tag: str, *conds: Condition) -> RuleDraft:
    return RuleDraft(
        understood=True,
        clarification_ro="",
        name="n",
        zone_tag=zone_tag,
        all_of=list(conds),
        cooldown_s=120,
        explanation_ro="e",
    )


def test_anywhere_is_only_for_open_kinds() -> None:
    present = Condition(kind="present", role="guest", min_duration_s=60)
    with pytest.raises(TranslationError) as e:
        draft_to_rule(_draft(ANYWHERE_TAG, present), "cam1", "x", ZONES)
    assert e.value.code == "clarify"
    bear = Condition(kind="object_present", objects=["bear"])
    with pytest.raises(TranslationError):
        draft_to_rule(_draft(ANYWHERE_TAG, bear, present), "cam1", "x", ZONES)


def test_open_kinds_may_still_use_a_drawn_zone() -> None:
    dog = Condition(kind="object_present", objects=["dog"])
    assert draft_to_rule(_draft("entrance", dog), "cam1", "x", ZONES).zone_tag == "entrance"


def test_object_present_outside_coco_is_a_clarification() -> None:
    lion = Condition(kind="object_present", objects=["lion"])
    with pytest.raises(TranslationError) as e:
        draft_to_rule(_draft(ANYWHERE_TAG, lion), "cam1", "x", ZONES)
    assert e.value.code == "clarify"


def test_prompt_describes_both_new_situations_in_its_fixed_part() -> None:
    for needle in ("object_present", "visual", "positive", "negative", ANYWHERE_TAG, "bear"):
        assert needle in INSTRUCTIONS
    assert all(c in INSTRUCTIONS for c in COCO_CLASSES) and len(COCO_CLASSES) == 80
    assert "Masa 1" not in INSTRUCTIONS and "{" not in INSTRUCTIONS.split("## Output")[0][-200:]


def test_fire_rules_also_look_for_a_small_flame() -> None:
    rule = draft_to_rule(recorded("visual-fire"), "cam1", "x", ZONES)
    (c,) = rule.all_of
    assert c.positive[:3] == ["a photo of fire", "flames", "a burning fire"]
    assert set(SMALL_FLAME) <= set(c.positive)
    water = draft_to_rule(recorded("visual-water"), "cam1", "x", ZONES).all_of[0]
    assert not set(SMALL_FLAME) & set(water.positive)


@pytest.mark.parametrize(
    "negative",
    ["a photo of a person", "people sitting at tables", "A man", "a hand", "two guests"],
)
def test_person_prompts_never_stay_in_visual_negatives(negative: str) -> None:
    c = Condition(kind="visual", positive=["a knife"], negative=[negative, "a photo of a room"])
    assert clean_visual(c).negative == ["a photo of a room"]


def test_clean_visual_leaves_other_kinds_alone() -> None:
    bear = Condition(kind="object_present", objects=["bear"])
    assert clean_visual(bear) is bear


def test_prompt_keeps_people_out_of_negatives() -> None:
    assert "Never put a person or people in `negative`" in INSTRUCTIONS
    assert "a lighter with a flame" in INSTRUCTIONS
