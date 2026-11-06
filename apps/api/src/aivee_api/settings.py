from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    """Env: SITE, DEVICE, MQTT_HOST, MQTT_PORT, MQTT_API_USER, MQTT_API_PASSWORD, SNAPSHOT_DIR,
    CORS_ORIGINS, CLAUDE_MODEL, YOLO_WEIGHTS (+ POSTGRES_* via aivee_api.db.settings,
    ANTHROPIC_API_KEY read by the SDK itself)."""

    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    site: str = "demo"
    device: str = "edge-01"
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_api_user: str = "aivee-api"
    mqtt_api_password: str = ""
    mqtt_enabled: bool = True
    snapshot_dir: Path = Path("data/snapshots")
    """Relative to the repo root (where `make api` runs); compose bind-mounts the same dir."""
    cors_origins: list[str] = ["http://localhost:5173"]
    claude_model: str = "claude-opus-5-5"
    yolo_weights: str = "models/yolo11n.pt"
    default_profile_id: str = "staff"
    default_profile_name: str = "Personal"
