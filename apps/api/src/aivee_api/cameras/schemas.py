from datetime import datetime

from aivee_contracts.events import StreamState
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
    """A camera plus the device that serves it (dashboard `CameraView`).

    `online`: its device is online and its stream is not `down`. `stream_state`: what the
    edge last reported for this camera, `down` while its device is offline, None when unknown
    (an older edge, a clip or cloud camera, no status yet). `last_frame_at`: when the edge
    decoded its newest frame, as of that report; None when unknown or before the first one.
    """

    device: str = ""
    online: bool = False
    stream_state: StreamState | None = None
    last_frame_at: datetime | None = None
