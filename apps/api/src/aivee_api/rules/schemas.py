from aivee_contracts.rules import Action, Condition, Rule
from pydantic import BaseModel, Field


class RuleIn(BaseModel):
    id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    camera_id: str
    name: str = Field(min_length=1)
    prompt_ro: str = ""
    zone_tag: str = Field(min_length=1)
    all_of: list[Condition] = Field(min_length=1)
    action: Action = Field(default_factory=lambda: Action(type="telegram"))
    cooldown_s: int = Field(default=300, ge=0)
    enabled: bool = True


class RulePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    prompt_ro: str | None = None
    zone_tag: str | None = Field(default=None, min_length=1)
    all_of: list[Condition] | None = Field(default=None, min_length=1)
    action: Action | None = None
    cooldown_s: int | None = Field(default=None, ge=0)
    enabled: bool | None = None


class FromTextIn(BaseModel):
    camera_id: str
    text: str = Field(min_length=3, max_length=1000)
    save: bool = False


class FromTextOut(BaseModel):
    rule: Rule
    explanation_ro: str
    saved: bool
