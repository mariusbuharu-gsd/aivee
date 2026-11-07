"""Ingest writes device.online / device.offline to the audit history on a state change only."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from aivee_api.audit.models import AuditRow
from aivee_contracts.events import AlertEvent, DeviceStatus
from aivee_contracts.topics import Topics
from aivee_ingest.handler import IngestHandler
from sqlalchemy import select

pytestmark = pytest.mark.integration


class Quiet:
    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None: ...


async def _rows(sessions: Any) -> list[AuditRow]:
    async with sessions() as s:
        return list((await s.scalars(select(AuditRow).order_by(AuditRow.id))).all())


async def test_status_changes_are_audited_once(sessions: Any, tmp_path: Path) -> None:
    from aivee_api.accounts.models import Organization
    from aivee_api.db.models import Site

    async with sessions() as s:
        s.add(Organization(id="org", name="Org"))
        await s.flush()
        s.add(Site(id="demo", name="Demo", org_id="org"))
        await s.commit()
    topic = Topics(site="demo", device="edge-01").status
    online = DeviceStatus(device="edge-01", state="online").model_dump_json().encode()
    offline = DeviceStatus(device="edge-01", state="offline").model_dump_json().encode()
    # two replicas see every status message (non-shared subscription)
    a, b = IngestHandler(sessions, tmp_path, Quiet()), IngestHandler(sessions, tmp_path, Quiet())

    await asyncio.gather(a.handle(topic, online), b.handle(topic, online))
    await a.handle(topic, online)  # retained re-delivery: no change, no entry
    await asyncio.gather(a.handle(topic, offline), b.handle(topic, offline))

    rows = await _rows(sessions)
    assert [(r.kind, r.actor_kind, r.actor_id, r.location_id, r.org_id) for r in rows] == [
        ("device.online", "device", "edge-01", "demo", "org"),
        ("device.offline", "device", "edge-01", "demo", "org"),
    ]
    assert rows[1].summary_ro == "Dispozitivul edge-01 s-a deconectat"
    assert rows[1].before == {"state": "online"} and rows[1].after == {"state": "offline"}


async def test_unclaimed_site_is_audited_without_org(sessions: Any, tmp_path: Path) -> None:
    handler = IngestHandler(sessions, tmp_path, Quiet())
    status = DeviceStatus(device="edge-9", state="online").model_dump_json().encode()
    await handler.handle(Topics(site="new-site", device="edge-9").status, status)
    [row] = await _rows(sessions)
    assert (row.kind, row.location_id, row.org_id) == ("device.online", "new-site", None)
