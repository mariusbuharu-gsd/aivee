from pydantic import BaseModel


class ProfileOut(BaseModel):
    id: str
    name: str
    description_ro: str
    examples: int
    has_centroid: bool


class EnrolOut(BaseModel):
    profile: ProfileOut
    files: int
    frames: int
    crops: int
    examples_added: int
    skipped: list[str]
    published: bool


class DecisionOut(BaseModel):
    suggestion_id: str
    status: str
    examples_added: int = 0
