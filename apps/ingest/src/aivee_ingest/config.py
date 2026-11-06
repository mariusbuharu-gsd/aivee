from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestSettings(BaseSettings):
    """Env: MQTT_HOST, MQTT_PORT, MQTT_INGEST_USER, MQTT_INGEST_PASSWORD, SNAPSHOT_DIR,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_PREFIX, REALERT_AFTER_S
    (+ POSTGRES_* via aivee_api.db.settings,
    VAPID_* via aivee_api.push.settings for Web Push)."""

    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_ingest_user: str = "aivee-ingest"
    mqtt_ingest_password: str = ""
    mqtt_client_id: str | None = None
    snapshot_dir: Path = Path("data/snapshots")
    """Relative to the repo root (where `make api` runs); compose bind-mounts the same dir."""
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_prefix: str = ""
    """Prepended to every message, e.g. "[test]" when a dev run shares the real group."""
    realert_after_s: float = 120
    """Re-alert the whole location when nobody arrived this long after "Merg eu"."""
    realert_interval_s: float = 5
    """How often each replica looks for alerts to re-alert."""
