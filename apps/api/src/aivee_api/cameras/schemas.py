from aivee_contracts.geometry import CameraConfig, Zone
from pydantic import BaseModel, Field


class CameraIn(BaseModel):
    id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    name: str = Field(min_length=1)
    source: str = Field(min_length=1, description="RTSP/HTTP URL or device index")
    zones: list[Zone] = Field(default_factory=list)


class CameraOut(CameraConfig):
    """A camera plus the device that serves it (dashboard `CameraView`)."""

    device: str = ""
    online: bool = False
