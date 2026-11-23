"""Edge configuration from the environment (and `.env` when run from the repo root)."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from aivee_edge.redact import redact_url

ROTATIONS = (0, 90, 180, 270)

CAMERA_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
"""Same rule as the API's camera ids, so every CAMERAS id can be added in the dashboard."""


@dataclass(frozen=True)
class CameraSpec:
    """One camera this device reads: the id the dashboard and rules use, and its URL."""

    id: str
    source: str


def parse_cameras(text: str) -> list[CameraSpec]:
    """`cam-01=rtsp://…;cam-02=rtsp://…` → specs. Entries are separated by `;` or
    whitespace (newlines too), so a password must not contain a raw `;` or space:
    percent-encode it (`%3B`, `%20`). Errors never show a password."""
    specs: list[CameraSpec] = []
    for raw in re.split(r"[;\s]+", re.sub(r"\s*=\s*", "=", text.strip())):
        if not raw:
            continue
        camera_id, sep, source = raw.partition("=")
        if not sep or not CAMERA_ID.match(camera_id):
            raise ValueError(
                f"CAMERAS entry {redact_url(raw)!r}: expected <camera id>=<url>, the id made of "
                "letters, digits, '-' and '_'"
            )
        if not source:
            raise ValueError(f"CAMERAS entry {camera_id!r} has no URL")
        if any(s.id == camera_id for s in specs):
            raise ValueError(f"CAMERAS lists camera {camera_id!r} twice")
        specs.append(CameraSpec(camera_id, source))
    return specs


class EdgeSettings(BaseSettings):
    """Env: MQTT_HOST, MQTT_PORT, MQTT_TRANSPORT, MQTT_TLS, MQTT_WS_PATH, MQTT_EDGE_USER,
    MQTT_EDGE_PASSWORD, SITE, DEVICE, CAMERA_ID, SOURCE, CAMERAS, TARGET_FPS, ROTATE, ARRIVE_S,
    GRACE_S, DETECTOR_MODEL, POSE_MODEL, APPEARANCE, YUNET_MODEL, APPEARANCE_LOW, APPEARANCE_HIGH,
    STAFF_W_APPEARANCE, STAFF_W_STANDING, STAFF_W_BEHAVIOUR, CLIP_EPOCH, PROGRESS_FILE,
    CONFIG_WAIT_S, VISUAL_HZ."""

    # hide_input_in_errors: a bad value may be a camera URL or a password.
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True, hide_input_in_errors=True
    )

    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_transport: Literal["tcp", "websockets"] = "tcp"
    """`websockets` for a remote edge behind an HTTPS proxy (with MQTT_TLS=true, port 443)."""
    mqtt_tls: bool = False
    mqtt_ws_path: str = "/mqtt"
    mqtt_edge_user: str = "edge-01"
    mqtt_edge_password: str = ""

    site: str = "demo"
    device: str = ""
    """Defaults to the MQTT user: the broker ACL only lets a device write its own topics."""
    camera_id: str = "cam-01"

    source: str = "0"
    """Camera URL (RTSP/HTTP), a webcam index ("0"), a video file path, or
    `mqtt-frames://<camera_id>` (cloud mode: JPEGs the API relays over MQTT)."""
    cameras: str = ""
    """Several cameras on this device, one process: `cam-01=rtsp://…;cam-02=rtsp://…` (see
    `parse_cameras`). Used only when SOURCE is not given (env or --source), so the cloud
    vision worker, `make edge SOURCE=…` and clip runs keep their single camera."""
    target_fps: float = 10.0
    loop_file: bool = False
    rotate: int = 0
    """Clockwise rotation applied at capture: 0, 90, 180 or 270 (90 for a sideways phone)."""

    detector_model: str = "models/yolo11n_int8_openvino_model"
    pose_model: str = "models/yolo11n-pose_int8_openvino_model"
    """Empty disables pose (no raised-hand detection)."""
    appearance: bool = False
    """CLIP appearance scoring (~0.6 s per crop on CPU, rate-limited per track)."""
    appearance_low: float = 0.70
    """Best CLIP cosine to a staff profile mapped to appearance 0 (at or below)."""
    appearance_high: float = 0.82
    """Best CLIP cosine mapped to appearance 1 (at or above)."""
    staff_w_appearance: float = Field(0.60, ge=0)
    staff_w_standing: float = Field(0.25, ge=0)
    staff_w_behaviour: float = Field(0.15, ge=0)
    """Staff score fusion weights, normalised over the signals available per track."""
    visual_hz: float = Field(2.0, ge=0)
    """Visual rules ("dacă e foc"): CLIP scorings per second, on a background thread and
    only while an enabled visual rule exists. 0 turns visual rules off on this edge."""
    blur: bool = True
    yunet_model: str = "models/face_detection_yunet_2023mar.onnx"

    grace_s: float = 5.0
    """Seconds a person may be missing from a zone and still count as present: bridges detector
    flicker at low fps, so an alert closes about this long after the guest really leaves."""
    arrive_s: float = 5.0
    """Seconds a staff member must stay in an open alert's zone to count as arrived."""
    metrics_interval_s: float = 5.0

    clip_epoch: datetime | None = None
    """Offline clip analysis: event time = this instant + position in the clip, so the API
    can show each alert at its mm:ss. None (live): wall clock."""
    progress_file: str = ""
    """Offline clip analysis: JSON file the run keeps updated with how far it got."""
    config_wait_s: float = 0.0
    """Wait up to this long at start for the retained config (this camera) and rules; a run
    that gets neither exits with code 4. 0: start at once (live)."""

    @field_validator("rotate")
    @classmethod
    def _right_angle(cls, degrees: int) -> int:
        if degrees not in ROTATIONS:
            raise ValueError(f"ROTATE must be one of {ROTATIONS}")
        return degrees

    @model_validator(mode="after")
    def _appearance_band(self) -> "EdgeSettings":
        if self.appearance_high <= self.appearance_low:
            raise ValueError("APPEARANCE_HIGH must be greater than APPEARANCE_LOW")
        return self

    @model_validator(mode="after")
    def _some_weight(self) -> "EdgeSettings":
        if self.staff_w_appearance + self.staff_w_standing + self.staff_w_behaviour <= 0:
            raise ValueError("at least one STAFF_W_* weight must be positive")
        return self

    @model_validator(mode="after")
    def _device_from_user(self) -> "EdgeSettings":
        if not self.device:
            self.device = self.mqtt_edge_user
        return self

    @field_validator("cameras")
    @classmethod
    def _cameras_parse(cls, text: str) -> str:
        parse_cameras(text)
        return text

    @model_validator(mode="after")
    def _cameras_are_live(self) -> "EdgeSettings":
        if self.multi_camera and (self.clip_epoch is not None or self.progress_file):
            raise ValueError(
                "CAMERAS runs live cameras; an offline clip run takes SOURCE (or --source)"
            )
        return self

    @property
    def multi_camera(self) -> bool:
        """CAMERAS is set and SOURCE was not given: run every camera in one process."""
        return bool(parse_cameras(self.cameras)) and "source" not in self.model_fields_set

    def camera_specs(self) -> list[CameraSpec]:
        """The cameras this run reads: CAMERAS, or the single CAMERA_ID/SOURCE."""
        if self.multi_camera:
            return parse_cameras(self.cameras)
        return [CameraSpec(self.camera_id, self.source)]
