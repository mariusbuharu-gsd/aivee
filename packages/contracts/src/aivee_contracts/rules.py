from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

Role = Literal["guest", "staff", "any"]
ConditionKind = Literal[
    "present",
    "absent",
    "count",
    "pose",
    "objects_unattended",
    "object_gone",
    "object_present",
    "visual",
]
Crop = Literal["zone", "frame"]

OBJECT_KINDS: frozenset[str] = frozenset({"objects_unattended", "object_gone", "object_present"})

ANYWHERE_TAG = "anywhere"
"""Reserved `zone_tag`: the whole camera image, for rules that name no zone ("dacă e foc").
The edge adds a pseudo-zone with this tag (and id) covering the frame when a rule uses it;
nobody draws it, and its name is the camera's name."""

VISUAL_THRESHOLD = 0.5
"""Default `threshold` of a `visual` condition (see docs/handbook/backend.md, „Reguli libere”)."""


class Condition(BaseModel):
    """One fact about a zone that must hold for a rule to fire.

    - present: someone with `role` has been in the zone for at least `min_duration_s`
    - absent: nobody with `role` has been in the zone for at least `min_duration_s`
      (counted from when guests sat down, so "nobody came since they arrived")
    - count: at least `min_count` people with `role` are in the zone
    - pose: someone with `role` in the zone shows `pose`
    - objects_unattended: `objects` are in the zone and no person has been there
      for at least `min_duration_s`
    - object_gone: an object of `objects` was in the zone for at least `min_duration_s`
      and has now been missing for a short confirm window (a few seconds, set by the
      edge), so detector flicker does not count as a disappearance
    - object_present: an object of `objects` (COCO class names, not "person") has been in
      the zone for at least `min_duration_s` ("a apărut un urs", "cineva are un cuțit")
    - visual: a zero-shot image check (CLIP) of the zone crop (or the whole frame) has
      scored the `positive` prompts above `threshold` against the `negative` ones for at
      least `min_duration_s`, continuously ("e foc", "e apă pe jos", "ușa e deschisă")
    """

    kind: ConditionKind
    role: Role = "any"
    min_duration_s: int = Field(default=0, ge=0)
    min_count: int = Field(default=1, ge=1)
    pose: Literal["raised_hand"] | None = None
    objects: list[str] = Field(default_factory=list, description="COCO class names")
    positive: list[str] = Field(
        default_factory=list,
        description='visual: English CLIP prompts of what to find, e.g. ["a photo of fire"]',
    )
    negative: list[str] = Field(
        default_factory=list,
        description='visual: English contrast prompts, e.g. ["a photo of a normal room"]',
    )
    threshold: float = Field(
        default=VISUAL_THRESHOLD,
        ge=0,
        le=1,
        description="visual: share of the softmax on the positive prompts needed to count",
    )
    crop: Crop | None = Field(
        default=None, description='visual: score the zone\'s box ("zone", default) or "frame"'
    )
    label_ro: str = Field(
        default="", description='Short Romanian name of what is looked for, e.g. "foc"'
    )

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.kind == "pose" and self.pose is None:
            raise ValueError("a pose condition needs 'pose'")
        if self.kind in OBJECT_KINDS and not self.objects:
            raise ValueError(f"an {self.kind} condition needs 'objects'")
        if self.kind == "object_present" and "person" in self.objects:
            raise ValueError("people are watched by present/absent/count, not object_present")
        if self.kind == "visual" and not [p for p in self.positive if p.strip()]:
            raise ValueError("a visual condition needs 'positive' prompts")
        return self


class Action(BaseModel):
    type: Literal["telegram", "push", "webhook"]
    target: str | None = None


class Rule(BaseModel):
    """A situation to watch for, evaluated once per zone carrying `zone_tag`."""

    id: str
    camera_id: str
    name: str
    prompt_ro: str = Field(description="The owner's original request, in Romanian")
    zone_tag: str
    all_of: list[Condition] = Field(min_length=1)
    action: Action
    cooldown_s: int = Field(default=300, ge=0)
    enabled: bool = True


class RuleSet(BaseModel):
    """Retained payload on the device's `rules` topic: the complete set."""

    device: str
    rules: list[Rule]
