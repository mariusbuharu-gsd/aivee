"""Edge configuration from the environment (and `.env` when run from the repo root)."""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EdgeSettings(BaseSettings):
    """Env: MQTT_HOST, MQTT_PORT, MQTT_EDGE_USER, MQTT_EDGE_PASSWORD, SITE, DEVICE,
    CAMERA_ID, SOURCE, TARGET_FPS, DETECTOR_MODEL, POSE_MODEL, APPEARANCE, YUNET_MODEL."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_edge_user: str = "edge-01"
    mqtt_edge_password: str = ""

    site: str = "demo"
    device: str = ""
    """Defaults to the MQTT user: the broker ACL only lets a device write its own topics."""
    camera_id: str = "cam-01"

    source: str = "0"
    """Camera URL (RTSP/HTTP), a webcam index ("0") or a video file path."""
    target_fps: float = 10.0
    loop_file: bool = False

    detector_model: str = "models/yolo11n_int8_openvino_model"
    pose_model: str = "models/yolo11n-pose_int8_openvino_model"
    """Empty disables pose (no raised-hand detection)."""
    appearance: bool = False
    """CLIP appearance scoring (~0.6 s per crop on CPU, rate-limited per track)."""
    blur: bool = True
    yunet_model: str = "models/face_detection_yunet_2023mar.onnx"

    grace_s: float = 1.5
    metrics_interval_s: float = 5.0

    @model_validator(mode="after")
    def _device_from_user(self) -> "EdgeSettings":
        if not self.device:
            self.device = self.mqtt_edge_user
        return self
