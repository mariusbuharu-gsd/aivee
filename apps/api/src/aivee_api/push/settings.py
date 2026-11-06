from pydantic_settings import BaseSettings, SettingsConfigDict


class VapidSettings(BaseSettings):
    """Env: VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT (`make vapid` fills them).

    Keys are base64url: the public key is the uncompressed P-256 point the browser needs as
    `applicationServerKey`, the private key is the raw 32-byte scalar.
    """

    model_config = SettingsConfigDict(env_prefix="VAPID_", extra="ignore", env_ignore_empty=True)

    public_key: str = ""
    private_key: str = ""
    subject: str = "mailto:aivee@example.com"

    @property
    def enabled(self) -> bool:
        return bool(self.public_key and self.private_key)
