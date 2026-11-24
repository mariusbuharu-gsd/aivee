"""R7: indices on the hot foreign keys, and location-scoped lists done in SQL."""

from typing import Any

import pytest
from aivee_api.db.repositories import CameraRepository, DeviceRepository, RuleRepository
from aivee_contracts.geometry import CameraConfig
from aivee_contracts.rules import Action, Condition, Rule
from sqlalchemy import text

pytestmark = pytest.mark.integration

EXPECTED = {
    ("events", "ix_events_device_id"),
    ("events", "ix_events_opened_lookup"),
    ("events", "ix_events_open_by_device"),
    ("devices", "ix_devices_site_id"),
    ("cameras", "ix_cameras_device_id"),
    ("rules", "ix_rules_camera_id"),
    ("suggestions", "ix_suggestions_device_id"),
    ("invites", "ix_invites_location_id"),
}


async def test_hot_foreign_keys_are_indexed(sessions: Any) -> None:
    async with sessions() as s:
        rows = await s.execute(text("SELECT tablename, indexname FROM pg_indexes"))
        present = {(t, i) for t, i in rows}
    assert present >= EXPECTED


async def _two_locations(sessions: Any) -> None:
    async with sessions() as s:
        for site, device, cam in (("loc-a", "edge-a", "cam-a"), ("loc-b", "edge-b", "cam-b")):
            await DeviceRepository(s).ensure_device(site, device)
            await CameraRepository(s).upsert(CameraConfig(id=cam, name=cam, source="x"), device)
            await RuleRepository(s).upsert(
                Rule(
                    id=f"r-{cam}",
                    camera_id=cam,
                    name="Mâna ridicată",
                    prompt_ro="",
                    zone_tag="table",
                    all_of=[Condition(kind="pose", role="guest", pose="raised_hand")],
                    action=Action(type="telegram"),
                )
            )
        await s.commit()


async def test_lists_are_scoped_to_one_location_in_the_query(sessions: Any) -> None:
    await _two_locations(sessions)
    async with sessions() as s:
        devices = await DeviceRepository(s).list_all(site_id="loc-a")
        cameras = await CameraRepository(s).list_all(location_id="loc-a")
        rules = await RuleRepository(s).list_all(location_id="loc-a")
        everything = await DeviceRepository(s).list_all()
    assert [d.id for d in devices] == ["edge-a"]
    assert [c.id for c in cameras] == ["cam-a"]
    assert [r.id for r in rules] == ["r-cam-a"]
    assert {d.id for d in everything} == {"edge-a", "edge-b"}
