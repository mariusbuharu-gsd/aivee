from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DbSettings(BaseSettings):
    """Postgres connection from POSTGRES_* env vars.

    Locally the compose stack exposes Postgres on POSTGRES_HOST_PORT; inside compose set
    POSTGRES_HOST=postgres and POSTGRES_PORT=5432. DATABASE_URL overrides everything.
    """

    model_config = SettingsConfigDict(env_prefix="POSTGRES_", extra="ignore")

    host: str = "localhost"
    port: int | None = None
    host_port: int = 5433
    db: str = "aivee"
    user: str = "aivee"
    password: str = ""
    database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")

    @property
    def url(self) -> str:
        if self.database_url:
            return self.database_url
        port = self.port or self.host_port
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{port}/{self.db}"
