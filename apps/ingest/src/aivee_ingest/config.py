from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestSettings(BaseSettings):
    """Env: MQTT_HOST, MQTT_PORT, MQTT_INGEST_USER, MQTT_INGEST_PASSWORD, SNAPSHOT_DIR,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (+ POSTGRES_* via aivee_api.db.settings)."""

    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_ingest_user: str = "aivee-ingest"
    mqtt_ingest_password: str = ""
    mqtt_client_id: str | None = None
    snapshot_dir: Path = Path("snapshots")
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
