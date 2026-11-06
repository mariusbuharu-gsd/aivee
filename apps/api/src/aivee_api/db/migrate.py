"""Run Alembic programmatically: `python -m aivee_api.db.migrate [upgrade|downgrade] [rev]`."""

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"


def alembic_config(url: str | None = None) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    if url:
        cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def upgrade(url: str | None = None, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str | None = None, revision: str = "base") -> None:
    command.downgrade(alembic_config(url), revision)


def main(argv: list[str]) -> None:
    action = argv[0] if argv else "upgrade"
    if action == "upgrade":
        upgrade(revision=argv[1] if len(argv) > 1 else "head")
    elif action == "downgrade":
        downgrade(revision=argv[1] if len(argv) > 1 else "base")
    else:
        raise SystemExit(f"unknown action {action!r}; use upgrade or downgrade")


if __name__ == "__main__":
    main(sys.argv[1:])
