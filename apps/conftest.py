"""Shared integration fixtures: Postgres+pgvector and Mosquitto in testcontainers.

Both use random host ports, so they never collide with the dev compose stack. Mosquitto runs
with the real `infra/mosquitto` config, entrypoint and ACL, and generated test passwords.
"""

import asyncio
import secrets
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

INFRA = Path(__file__).resolve().parents[1] / "infra" / "mosquitto"


@dataclass(frozen=True)
class Broker:
    host: str
    port: int
    api: tuple[str, str]
    ingest: tuple[str, str]
    edge: tuple[str, str]  # username == device id (ACL %u)


@pytest.fixture(scope="session")
def broker() -> Iterator[Broker]:
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.wait_strategies import LogMessageWaitStrategy

    creds = {
        "api": ("aivee-api", secrets.token_urlsafe(12)),
        "ingest": ("aivee-ingest", secrets.token_urlsafe(12)),
        "edge": ("edge-01", secrets.token_urlsafe(12)),
    }
    container = (
        DockerContainer("eclipse-mosquitto:2")
        .with_volume_mapping(str(INFRA / "mosquitto.conf"), "/mosquitto/config/mosquitto.conf")
        .with_volume_mapping(str(INFRA / "acl"), "/mosquitto/config/acl")
        .with_volume_mapping(str(INFRA / "entrypoint.sh"), "/entrypoint.sh")
        .with_kwargs(entrypoint=["/bin/sh", "/entrypoint.sh"])
        .with_exposed_ports(1883)
        .waiting_for(LogMessageWaitStrategy("running").with_startup_timeout(30))
        .with_envs(
            MQTT_API_USER=creds["api"][0],
            MQTT_API_PASSWORD=creds["api"][1],
            MQTT_INGEST_USER=creds["ingest"][0],
            MQTT_INGEST_PASSWORD=creds["ingest"][1],
            MQTT_EDGE_USER=creds["edge"][0],
            MQTT_EDGE_PASSWORD=creds["edge"][1],
        )
    )
    with container:
        yield Broker(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(1883)),
            **creds,
        )


@pytest.fixture(scope="session")
def pg_server_url() -> Iterator[str]:
    """asyncpg URL of the server's default database."""
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg17", driver=None) as pg:
        yield pg.get_connection_url().replace("postgresql://", "postgresql+asyncpg://", 1)


async def _admin(server_url: str, sql: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(server_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.exec_driver_sql(sql)
    await engine.dispose()


@pytest.fixture
def empty_db_url(pg_server_url: str) -> Iterator[str]:
    """A fresh, empty database per test."""
    name = f"t_{uuid.uuid4().hex[:12]}"
    asyncio.run(_admin(pg_server_url, f'CREATE DATABASE "{name}"'))
    base, _, _ = pg_server_url.rpartition("/")
    yield f"{base}/{name}"
    asyncio.run(_admin(pg_server_url, f'DROP DATABASE "{name}" WITH (FORCE)'))


@pytest.fixture
def db_url(empty_db_url: str) -> str:
    """A fresh database migrated to head."""
    from aivee_api.db.migrate import upgrade

    upgrade(empty_db_url)
    return empty_db_url


@pytest.fixture
async def sessions(db_url: str) -> AsyncIterator[object]:
    from aivee_api.db.session import make_engine, make_session_factory

    engine = make_engine(db_url)
    yield make_session_factory(engine)
    await engine.dispose()


@pytest.fixture
def site() -> str:
    """A unique site per test, so retained messages never leak between tests."""
    return f"site-{uuid.uuid4().hex[:8]}"
