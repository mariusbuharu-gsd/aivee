from aivee_contracts.geometry import CameraConfig, Zone
from pydantic import BaseModel, Field

ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class CameraIn(BaseModel):
    id: str | None = Field(default=None, pattern=ID_PATTERN)
    name: str = Field(min_length=1)
    source: str = Field(min_length=1, description="RTSP/HTTP URL or device index")
    zones: list[Zone] = Field(default_factory=list)
    device: str | None = Field(
        default=None, pattern=ID_PATTERN, description="Edge device id; default: the API's DEVICE"
    )


class CameraPatch(BaseModel):
    """Fields left out stay as they are; zones change only through `/zones`."""

    name: str | None = Field(default=None, min_length=1)
    source: str | None = Field(default=None, min_length=1)
    device: str | None = Field(default=None, pattern=ID_PATTERN)


class CameraOut(CameraConfig):
    """A camera plus the device that serves it (dashboard `CameraView`)."""

    device: str = ""
    online: bool = False
