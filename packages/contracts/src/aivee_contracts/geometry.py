from pydantic import BaseModel, Field, field_validator

Point = tuple[float, float]
"""A point in normalised image coordinates: (x, y), both in [0, 1]."""


class Zone(BaseModel):
    """A named area drawn on a camera image, e.g. a table or the entrance."""

    id: str
    name: str
    tag: str = Field(description='Zone kind used by rules: "table", "entrance", "staff"…')
    polygon: list[Point] = Field(min_length=3)

    @field_validator("polygon")
    @classmethod
    def _normalised(cls, points: list[Point]) -> list[Point]:
        if any(not 0 <= c <= 1 for p in points for c in p):
            raise ValueError("coordinates must be normalised to [0, 1]")
        return points


class CameraConfig(BaseModel):
    """What an edge device needs to know about one camera."""

    id: str
    name: str
    source: str = Field(description="RTSP/HTTP URL or device index")
    zones: list[Zone] = Field(default_factory=list)
