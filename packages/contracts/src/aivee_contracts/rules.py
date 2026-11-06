from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

Role = Literal["guest", "staff", "any"]
ConditionKind = Literal["present", "absent", "count", "pose", "objects_unattended", "object_gone"]

OBJECT_KINDS: frozenset[str] = frozenset({"objects_unattended", "object_gone"})


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
    """

    kind: ConditionKind
    role: Role = "any"
    min_duration_s: int = Field(default=0, ge=0)
    min_count: int = Field(default=1, ge=1)
    pose: Literal["raised_hand"] | None = None
    objects: list[str] = Field(default_factory=list, description="COCO class names")

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.kind == "pose" and self.pose is None:
            raise ValueError("a pose condition needs 'pose'")
        if self.kind in OBJECT_KINDS and not self.objects:
            raise ValueError(f"an {self.kind} condition needs 'objects'")
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
