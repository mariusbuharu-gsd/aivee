from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestSettings(BaseSettings):
    """Env: MQTT_HOST, MQTT_PORT, MQTT_INGEST_USER, MQTT_INGEST_PASSWORD, SNAPSHOT_DIR,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_SINGLE_TENANT, TELEGRAM_PREFIX, TELEGRAM_POLL,
    PUBLIC_DASHBOARD_URL,
    REALERT_AFTER_S, REMIND_S, NOTIFY_WORKERS, NOTIFY_QUEUE_SIZE, NOTIFY_ATTEMPTS,
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
    """A shared chat, used only with `telegram_single_tenant` (dev or a one-customer install)."""
    telegram_single_tenant: bool = False
    """True: alerts of a location without its own chat go to TELEGRAM_CHAT_ID. Off (the
    default), they go to no chat at all: a shared chat would show one customer's alerts to
    another."""
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
    remind_s: float = 120
    """Remind the location every this many seconds while an alert is open and nobody
    arrived ("⏰ Încă neservit"); 0 turns reminders off."""
    realert_interval_s: float = 5
    notify_workers: int = 8
    """Notification workers (R3): an alert's jobs always run on the same one, in order."""
    notify_queue_size: int = 100
    """Jobs waiting per worker; beyond it a job is dropped (`notify_dropped`), never awaited."""
    notify_attempts: int = 3
    """Tries per channel send (Telegram, Web Push), with backoff 1 s, 2 s, ... up to 10 s."""
    """How often each replica looks for alerts to re-alert."""
    verify_alerts: bool = False
    """Ask a vision model whether each opened alert's image(s) really show the situation."""
    verify_model: str = "claude-opus-5-5"
    verify_timeout_s: float = 20
    """Longer than this and the alert goes out unverified."""
    anthropic_api_key: str | None = None

    @property
    def telegram_fallback_chat(self) -> str | None:
        """The chat for alerts of a location without its own: only in single-tenant mode."""
        return self.telegram_chat_id if self.telegram_single_tenant else None
