from pathlib import Path
from typing import Annotated, Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class ApiSettings(BaseSettings):
    """Env: SITE, DEVICE, MQTT_HOST, MQTT_PORT, MQTT_API_USER, MQTT_API_PASSWORD, SNAPSHOT_DIR,
    CORS_ORIGINS (comma-separated), COOKIE_SECURE, SESSION_TTL_HOURS, DASHBOARD_URL,
    CLAUDE_MODEL, YOLO_WEIGHTS (+ POSTGRES_* via aivee_api.db.settings,
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
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://localhost:5174",
    ]
    cookie_secure: bool = False
    session_ttl_hours: float = 12
    invite_ttl_days: int = 7
    dashboard_url: str | None = None
    """Base URL of invite links; defaults to the first CORS origin."""
    claude_model: str = "claude-opus-5-5"
    yolo_weights: str = "models/yolo11n.pt"
    default_profile_id: str = "staff"
    default_profile_name: str = "Personal"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [o.strip() for o in value.split(",") if o.strip()]
        return value

    @property
    def invite_base_url(self) -> str:
        return (self.dashboard_url or self.cors_origins[0]).rstrip("/")
