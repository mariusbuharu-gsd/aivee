from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class DbSettings(BaseSettings):
    """Postgres connection from POSTGRES_* env vars.

    Locally the compose stack exposes Postgres on POSTGRES_HOST_PORT; inside compose set
    POSTGRES_HOST=postgres and POSTGRES_PORT=5432. DATABASE_URL overrides everything.
    """

    model_config = SettingsConfigDict(env_prefix="POSTGRES_", extra="ignore", env_ignore_empty=True)

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
        return URL.create(
            "postgresql+asyncpg",
            username=self.user,
            password=self.password,  # URL.create escapes special characters
            host=self.host,
            port=self.port or self.host_port,
            database=self.db,
        ).render_as_string(hide_password=False)
