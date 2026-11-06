"""An uploaded clip must never ring the staff's phones: no alert push or Telegram, no
arrival follow-up, no device note, no re-alert, no alert audit entries, and its open
alerts are left for the API to close as `video_end` when the device goes offline."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from aivee_api.alerts.audit import RepositoryAuditWriter
from aivee_api.alerts.repository import AlertRepository
from aivee_api.audit.models import AuditRow
from aivee_api.db.models import EventRow
from aivee_api.db.repositories import DeviceRepository
from aivee_api.push.sender import PushKind
from aivee_contracts.events import AlertEvent, DeviceStatus
from aivee_contracts.topics import Topics
from aivee_ingest.handler import IngestHandler
from aivee_ingest.realert import Realerter
from sqlalchemy import select, update

pytestmark = pytest.mark.integration

SITE = "demo"
T0 = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=10)


class Notifier:
    def __init__(self) -> None:
        self.alerts: list[AlertEvent] = []
        self.texts: list[str] = []

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        self.alerts.append(event)

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None, kind: PushKind
    ) -> None:
        self.texts.append(text)


def _event(camera: str, state: str, at: datetime, event_id: str | None = None) -> bytes:
    return (
        AlertEvent.model_validate(
            {
                "event_id": event_id or str(uuid.uuid4()),
                "rule_id": "r1",
                "camera_id": camera,
                "zone_id": "t1",
                "state": state,
                "at": at,
                "summary_ro": "Masa 1: neservită de 1 min",
            }
        )
        .model_dump_json()
        .encode()
    )


def _status(device: str, state: str) -> bytes:
    return (
        DeviceStatus.model_validate(
            {"device": device, "state": state, "version": "t", "cameras": []}
        )
        .model_dump_json()
        .encode()
    )


async def _seed(sessions: Any) -> None:
    from aivee_api.accounts.models import Organization
    from aivee_api.db.models import Site

    async with sessions() as s:
        s.add(Organization(id="org", name="Org"))
        await s.flush()
        s.add(Site(id=SITE, name="Demo", org_id="org"))
        await DeviceRepository(s).ensure_device(SITE, "edge-01")
        await DeviceRepository(s).ensure_device(SITE, "upload-01")
        await s.commit()


async def test_upload_events_are_stored_but_nobody_is_notified(
    sessions: Any, tmp_path: Path
) -> None:
    await _seed(sessions)
    notifier = Notifier()
    handler = IngestHandler(sessions, tmp_path, notifier, audit=RepositoryAuditWriter())
    up = Topics(site=SITE, device="upload-01")
    live = Topics(site=SITE, device="edge-01")

    await handler.handle(up.status, _status("upload-01", "online"))
    await handler.handle(up.events, _event("video-abc", "opened", T0, "ev-up"))
    await handler.handle(up.events, _event("video-abc", "arrived", T0 + timedelta(seconds=20)))
    await handler.handle(up.events, _event("video-abc", "opened", T0 + timedelta(seconds=40)))
    await handler.handle(up.status, _status("upload-01", "offline"))
    assert notifier.alerts == [] and notifier.texts == []

    # The same messages from a live edge do notify: the guard is about uploads only.
    await handler.handle(live.events, _event("cam-01", "opened", T0, "ev-live"))
    assert [e.event_id for e in notifier.alerts] == ["ev-live"]

    async with sessions() as s:
        rows = (await s.scalars(select(EventRow).where(EventRow.device_id == "upload-01"))).all()
        assert len(rows) == 3
        opened = [r for r in rows if r.state == "opened"]
        assert all(r.closed_at is None for r in opened)  # left for the API (video_end)
        assert next(r for r in opened if r.event_id == "ev-up").arrived_at is not None
        audit = (await s.scalars(select(AuditRow))).all()
        assert [(a.kind, a.actor_id) for a in audit] == [("alert.opened", "edge-01")]


async def test_an_acknowledged_upload_alert_is_never_realerted(
    sessions: Any, tmp_path: Path
) -> None:
    await _seed(sessions)
    handler = IngestHandler(sessions, tmp_path, Notifier())
    up = Topics(site=SITE, device="upload-01")
    await handler.handle(up.events, _event("video-abc", "opened", T0, "ev-up"))
    async with sessions() as s:
        await s.execute(
            update(EventRow).where(EventRow.event_id == "ev-up").values(acknowledged_at=T0)
        )
        await s.commit()
    notifier = Notifier()
    realerter = Realerter(sessions, notifier, RepositoryAuditWriter(), after_s=60)
    assert await realerter.tick() == []
    assert notifier.texts == []
    async with sessions() as s:
        view = await AlertRepository(s).view("ev-up")
        assert view is not None and view.realerted_at is None
