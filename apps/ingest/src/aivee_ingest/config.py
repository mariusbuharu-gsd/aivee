from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestSettings(BaseSettings):
    """Env: MQTT_HOST, MQTT_PORT, MQTT_INGEST_USER, MQTT_INGEST_PASSWORD, SNAPSHOT_DIR,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_PREFIX, TELEGRAM_POLL, PUBLIC_DASHBOARD_URL,
    REALERT_AFTER_S,
    VERIFY_ALERTS, VERIFY_MODEL, VERIFY_TIMEOUT_S, ANTHROPIC_API_KEY
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
    telegram_poll: bool = True
    """Run the "Conectează Telegram" getUpdates poller (one replica polls, by advisory lock)."""
    public_dashboard_url: str | None = None
    """The dashboard's public https URL for the "Vezi în aplicație" button; anything else
    (empty, http, localhost, a private IP) leaves the button out, since Telegram rejects
    the whole message over a bad button URL."""
    realert_after_s: float = 120
    """Re-alert the whole location when nobody arrived this long after "Merg eu"."""
    realert_interval_s: float = 5
    """How often each replica looks for alerts to re-alert."""
    verify_alerts: bool = False
    """Ask a vision model whether each opened alert's image(s) really show the situation."""
    verify_model: str = "claude-opus-5-5"
    verify_timeout_s: float = 20
    """Longer than this and the alert goes out unverified."""
    anthropic_api_key: str | None = None
