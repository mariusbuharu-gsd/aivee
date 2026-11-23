"""What the API sends an edge device on `commands`, and what the edge answers on `replies`.

Two kinds of message share the `commands` topic, told apart by `kind`:

- `EdgeCommand`: the owner decided a staff suggestion (fire and forget).
- `EdgeRequest`: a one-off job the API waits for (camera discovery, camera test). The edge
  answers with one `EdgeReply` on `replies`, carrying the same `request_id`.

`parse_command` reads either from a payload.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, model_validator

CommandKind = Literal["confirm_staff", "reject_staff"]


class EdgeCommand(BaseModel):
    """Sent by the API on `commands` (QoS 1, not retained): the owner decided a suggestion."""

    command_id: str = Field(description="UUID; lets the edge drop a redelivered command")
    kind: CommandKind
    camera_id: str
    track_id: int
    suggestion_id: str
    at: datetime


RequestKind = Literal["discover_cameras", "test_camera"]


class EdgeRequest(BaseModel):
    """Sent by the API on `commands` (QoS 1, not retained): a one-off job for the edge.

    discover_cameras: look for IP cameras on the device's network · test_camera: open
    `source` once and send back one face-blurred still. The edge answers on `replies`.
    """

    request_id: str = Field(description="UUID; the reply carries it back")
    kind: RequestKind
    at: datetime
    source: str | None = Field(
        default=None, description="test_camera: the camera URL, credentials included"
    )

    @model_validator(mode="after")
    def _test_needs_source(self) -> "EdgeRequest":
        if self.kind == "test_camera" and not self.source:
            raise ValueError("test_camera needs a source")
        return self


_ANY_COMMAND: TypeAdapter[EdgeCommand | EdgeRequest] = TypeAdapter(
    Annotated[EdgeCommand | EdgeRequest, Field(discriminator="kind")]
)


def parse_command(payload: str | bytes) -> EdgeCommand | EdgeRequest:
    """A message from `commands`; raises `pydantic.ValidationError` when it is neither."""
    return _ANY_COMMAND.validate_json(payload)


CameraBrand = Literal["tapo", "hikvision", "dahua", "reolink", "unknown"]


class DiscoveredCamera(BaseModel):
    """An IP camera the edge found on its network (ONVIF discovery or an open RTSP port)."""

    ip: str
    port: int = Field(default=554, ge=1, le=65535, description="RTSP port")
    brand: CameraBrand = "unknown"
    model: str | None = None
    name: str | None = None
    onvif: bool = Field(default=False, description="Answered an ONVIF WS-Discovery probe")
    rtsp_paths: list[str] = Field(
        default_factory=list, description="Suggested RTSP paths, substream first"
    )


ReplyError = Literal[
    "camera_auth",
    "camera_unreachable",
    "camera_no_stream",
    "bad_request",
    "failed",
]
"""camera_auth: the camera refused the user or password · camera_unreachable: no answer at
that address · camera_no_stream: it answered but sent no picture (wrong path) ·
bad_request: the request made no sense to the edge · failed: the job broke on the edge."""


class EdgeReply(BaseModel):
    """Published by the edge on `replies` (QoS 1, not retained), one per `EdgeRequest`."""

    request_id: str
    kind: RequestKind
    device: str
    ok: bool
    error: ReplyError | None = None
    cameras: list[DiscoveredCamera] = Field(
        default_factory=list, description="discover_cameras: what was found"
    )
    jpeg_b64: str | None = Field(
        default=None, description="test_camera: the face-blurred still, base64 JPEG"
    )
    width: int | None = Field(default=None, description="test_camera: the stream's frame width")
    height: int | None = Field(default=None, description="test_camera: the stream's frame height")
    frame_at: datetime | None = Field(default=None, description="test_camera: when it was taken")
    at: datetime
