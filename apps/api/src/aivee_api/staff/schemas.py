from pydantic import BaseModel, Field

from aivee_api.cameras.schemas import ID_PATTERN
from aivee_api.staff.capture import CAPTURE_DEFAULT_S, CAPTURE_MAX_S, CAPTURE_MIN_S

PROFILE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


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


class CaptureIn(BaseModel):
    camera_id: str = Field(pattern=ID_PATTERN)
    seconds: int = Field(default=CAPTURE_DEFAULT_S, ge=CAPTURE_MIN_S, le=CAPTURE_MAX_S)


class CaptureCandidate(BaseModel):
    index: int
    thumbnail: str
    """`data:image/jpeg;base64,…` of the person crop."""


class CaptureOut(BaseModel):
    token: str
    camera_id: str
    frames: int
    candidates: list[CaptureCandidate]
    expires_in_s: int


class CaptureConfirmIn(BaseModel):
    keep: list[int] = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=80)
    description_ro: str = Field(default="", max_length=300)
    profile_id: str | None = Field(default=None, pattern=PROFILE_ID_PATTERN)
