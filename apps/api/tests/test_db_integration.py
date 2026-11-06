import asyncio
import math
import uuid
from datetime import UTC, datetime

import pytest
from aivee_api.db.migrate import downgrade, upgrade
from aivee_api.db.repositories import (
    CameraRepository,
    DeviceRepository,
    EventRepository,
    RuleRepository,
    StaffRepository,
    SuggestionRepository,
)
from aivee_contracts.events import AlertEvent, DeviceStatus, StaffSuggestion
from aivee_contracts.geometry import CameraConfig, Zone
from aivee_contracts.rules import Action, Condition, Rule
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.integration

TABLES = {
    "sites",
    "devices",
    "cameras",
    "rules",
    "events",
    "staff_profiles",
    "staff_examples",
    "suggestions",
    "push_subscriptions",
}


async def _tables(url: str) -> set[str]:
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        names = {r[0] for r in rows}
    await engine.dispose()
    return names - {"alembic_version"}


def _event(event_id: str | None = None, state: str = "opened") -> AlertEvent:
    return AlertEvent.model_validate(
        {
            "event_id": event_id or str(uuid.uuid4()),
            "rule_id": "r1",
            "camera_id": "cam1",
            "zone_id": "t1",
            "state": state,
            "at": datetime.now(UTC),
            "summary_ro": "Masa 1 așteaptă de 5 minute",
        }
    )


def _unit(*hot: int) -> list[float]:
    v = [0.0] * 512
    for i in hot:
        v[i] = 1.0
    n = math.sqrt(len(hot))
    return [x / n for x in v]


def test_migration_upgrade_and_downgrade(empty_db_url: str) -> None:
    # Sync test: Alembic's async env runs its own event loop.
    upgrade(empty_db_url)
    assert asyncio.run(_tables(empty_db_url)) == TABLES
    downgrade(empty_db_url)
    assert asyncio.run(_tables(empty_db_url)) == set()
    upgrade(empty_db_url)
    assert asyncio.run(_tables(empty_db_url)) == TABLES


async def test_duplicate_event_is_stored_once(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    event = _event()
    async with sessions() as s:
        repo = EventRepository(s)
        assert await repo.insert_if_new(event, "edge-01") is True
        assert await repo.insert_if_new(event, "edge-01") is False
        await s.commit()
    async with sessions() as s:
        count = await s.scalar(text("SELECT count(*) FROM events"))
        stored = await EventRepository(s).get(event.event_id)
    assert count == 1
    assert stored is not None and stored.summary_ro == event.summary_ro


async def test_device_status_upsert(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as s:
        repo = DeviceRepository(s)
        await repo.apply_status("s1", DeviceStatus(device="edge-01", state="online"))
        await repo.apply_status("s1", DeviceStatus(device="edge-01", state="offline"))
        await s.commit()
        device = await repo.get("edge-01")
    assert device is not None and device.state == "offline" and device.last_seen is not None


async def test_camera_rule_and_suggestion_roundtrip(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    camera = CameraConfig(
        id="cam1",
        name="Sala",
        source="rtsp://cam/1",
        zones=[Zone(id="t1", name="Masa 1", tag="table", polygon=[(0, 0), (1, 0), (1, 1)])],
    )
    rule = Rule(
        id="r1",
        camera_id="cam1",
        name="Așteptare",
        prompt_ro="Anunță-mă dacă nu vine nimeni la masă 5 minute",
        zone_tag="table",
        all_of=[Condition(kind="absent", role="staff", min_duration_s=300)],
        action=Action(type="telegram"),
    )
    suggestion = StaffSuggestion(
        suggestion_id="sg1", camera_id="cam1", track_id=7, staff_score=0.8, reason_ro="tricou"
    )
    async with sessions() as s:
        await CameraRepository(s).upsert(camera)
        await RuleRepository(s).upsert(rule)
        sug = SuggestionRepository(s)
        assert await sug.insert_if_new(suggestion, "edge-01") is True
        assert await sug.insert_if_new(suggestion, "edge-01") is False
        await sug.set_status("sg1", "confirmed")
        await s.commit()
    async with sessions() as s:
        stored_cam = await CameraRepository(s).get("cam1")
        rules = await RuleRepository(s).for_camera("cam1")
        pending = await SuggestionRepository(s).pending()
    assert stored_cam is not None and stored_cam.zones[0]["id"] == "t1"
    assert rules == [rule]
    assert pending == []


async def test_pgvector_nearest_profile(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as s:
        repo = StaffRepository(s)
        assert await repo.nearest_profile(_unit(0)) is None
        await repo.create_profile("waiter", "Ospătar", "tricou negru")
        await repo.create_profile("cook", "Bucătar", "șorț alb")
        await repo.add_example("waiter", _unit(0))
        await repo.add_example("waiter", _unit(0, 1))
        await repo.recompute_centroid("waiter")
        await repo.set_centroid("cook", _unit(100))
        await s.commit()
        nearest = await repo.nearest_profile(_unit(1))
    assert nearest is not None
    profile, distance = nearest
    assert profile.id == "waiter"
    assert 0 <= distance < 1
