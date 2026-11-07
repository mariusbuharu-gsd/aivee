"""Opened alert → ingest → verification stored on the alert row → AlertView, metrics, feed."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from aivee_api.alerts.live import AlertFeed
from aivee_api.alerts.repository import AlertRepository
from aivee_api.db.models import Camera, RuleRow
from aivee_api.db.repositories import DeviceRepository
from aivee_api.push.sender import PushKind
from aivee_contracts.events import AlertEvent, ObjectChange, Verification, before_snapshot_id
from aivee_contracts.topics import Topics
from aivee_ingest.handler import IngestHandler
from aivee_ingest.verify import AlertVerification, DbVerificationStore, VerifyKind

pytestmark = pytest.mark.integration

SITE, DEVICE = "demo", "edge-01"
T = Topics(site=SITE, device=DEVICE)
PROMPT = "Anunță-mă dacă dispare un pahar de pe masă"


class Notifier:
    def __init__(self) -> None:
        self.opened: list[AlertEvent] = []

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        self.opened.append(event)

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None, kind: PushKind
    ) -> None:
        pass


class Verifier:
    def __init__(self, status: str) -> None:
        self.status = status
        self.asked: list[tuple[str, str, int, VerifyKind]] = []

    async def verify(
        self,
        rule_prompt_ro: str,
        zone_name: str,
        images: Sequence[bytes],
        kind: VerifyKind,
        objects: Sequence[str] = (),
    ) -> Verification:
        self.asked.append((rule_prompt_ro, zone_name, len(images), kind))
        return Verification.model_validate(
            {"status": self.status, "summary_ro": f"{zone_name}: a dispărut paharul de vin"}
        )


async def _seed(sessions: Any) -> None:
    from aivee_api.accounts.models import Organization
    from aivee_api.db.models import Site

    async with sessions() as s:
        s.add(Organization(id="org", name="Org"))
        await s.flush()
        s.add(Site(id=SITE, name="Demo", org_id="org"))
        await DeviceRepository(s).ensure_device(SITE, DEVICE)
        zone = {"id": "t1", "name": "Masa 1", "tag": "table", "polygon": [[0, 0], [1, 0], [1, 1]]}
        s.add(Camera(id="cam1", name="Sala", source="0", device_id=DEVICE, zones=[zone]))
        await s.flush()
        s.add(RuleRow(id="r1", camera_id="cam1", rule={"name": "Pahar"}, prompt_ro=PROMPT))
        await s.commit()


def _gone_event() -> AlertEvent:
    return AlertEvent(
        event_id=str(uuid.uuid4()),
        rule_id="r1",
        camera_id="cam1",
        zone_id="t1",
        state="opened",
        at=datetime.now(UTC),
        summary_ro="Masa 1: a dispărut paharul de vin",
        snapshot=True,
        object_change=ObjectChange(objects=["wine glass"], before_snapshot=True),
    )


async def _handle(handler: IngestHandler, event: AlertEvent, tmp: Path) -> None:
    await handler.handle(T.snapshot(event.event_id), b"\xff\xd8after")
    await handler.handle(T.snapshot_before(event.event_id), b"\xff\xd8before")
    assert (tmp / f"{before_snapshot_id(event.event_id)}.jpg").is_file()
    await handler.handle(T.events, event.model_dump_json().encode())
    await handler.drain()


@pytest.mark.parametrize(("status", "notified"), [("confirmed", 1), ("rejected", 0)])
async def test_verified_object_gone_alert(
    sessions: Any, tmp_path: Path, status: str, notified: int
) -> None:
    await _seed(sessions)
    feed = AlertFeed(sessions)
    await feed.start()
    notifier, verifier = Notifier(), Verifier(status)
    verification = AlertVerification(verifier, DbVerificationStore(sessions), notifier, tmp_path)
    handler = IngestHandler(sessions, tmp_path, notifier, verification=verification)
    event = _gone_event()

    await _handle(handler, event, tmp_path)

    assert verifier.asked == [(PROMPT, "Masa 1", 2, "object_gone")]
    assert len(notifier.opened) == notified
    async with sessions() as s:
        view = await AlertRepository(s).view(event.event_id)
        counts = await AlertRepository(s).verification_counts([SITE])
    assert view is not None and view.verification is not None
    assert view.verification.status == status
    assert view.verification.latency_ms is not None
    assert view.before_snapshot_url == f"/api/snapshots/{event.event_id}-before"
    assert counts == [("r1", status, 1)]
    # The dashboard hears about the verification.
    assert [m.data.verification for m in await feed.poll()][-1] == view.verification


async def test_without_a_verifier_alerts_are_unavailable_and_notified_at_once(
    sessions: Any, tmp_path: Path
) -> None:
    await _seed(sessions)
    notifier = Notifier()
    handler = IngestHandler(sessions, tmp_path, notifier)
    event = _gone_event()

    await _handle(handler, event, tmp_path)

    assert len(notifier.opened) == 1
    async with sessions() as s:
        view = await AlertRepository(s).view(event.event_id)
    assert view is not None and view.verification is not None
    assert view.verification.status == "unavailable"
