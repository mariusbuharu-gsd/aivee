"""S4: a snapshot is stored under the site and device of its topic, so one device can never
overwrite (or lend its image to) another device's event."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from aivee_api.push.sender import PushKind
from aivee_contracts.events import AlertEvent
from aivee_contracts.topics import Topics
from aivee_ingest.handler import IngestHandler
from sqlalchemy import text

A = Topics(site="loc-a", device="edge-a")
B = Topics(site="loc-b", device="edge-b")


class Recording:
    def __init__(self) -> None:
        self.snapshots: list[bytes | None] = []

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        self.snapshots.append(snapshot.read_bytes() if snapshot else None)

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None, kind: PushKind
    ) -> None:
        pass


def _handler(tmp_path: Path, sessions: Any = None, notifier: Any = None) -> IngestHandler:
    return IngestHandler(sessions, tmp_path, notifier or Recording(), snapshot_wait_s=0.5)


async def test_snapshots_are_stored_per_site_and_device(tmp_path: Path) -> None:
    handler = _handler(tmp_path)
    await handler.handle(A.snapshot("ev-1"), b"\xff\xd8from-a")
    await handler.handle(B.snapshot("ev-1"), b"\xff\xd8from-b")  # B reuses A's event id
    assert (tmp_path / "loc-a" / "edge-a" / "ev-1.jpg").read_bytes() == b"\xff\xd8from-a"
    assert (tmp_path / "loc-b" / "edge-b" / "ev-1.jpg").read_bytes() == b"\xff\xd8from-b"
    assert not (tmp_path / "ev-1.jpg").exists()


@pytest.mark.parametrize(
    ("site", "device", "snapshot_id"),
    [("..", "edge-a", "ev-1"), ("loc-a", "..", "ev-1"), ("loc a", "edge-a", "ev-1")],
)
async def test_unsafe_topic_segments_store_nothing(
    tmp_path: Path, site: str, device: str, snapshot_id: str
) -> None:
    handler = _handler(tmp_path / "snap")
    await handler.handle(f"aivee/{site}/{device}/snapshots/{snapshot_id}", b"\xff\xd8x")
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


@pytest.mark.integration
async def test_another_devices_snapshot_never_reaches_the_event(
    sessions: Any, tmp_path: Path
) -> None:
    notifier = Recording()
    handler = _handler(tmp_path, sessions, notifier)
    event = AlertEvent(
        event_id=str(uuid.uuid4()),
        rule_id="r1",
        camera_id="cam1",
        zone_id="t1",
        state="opened",
        at=datetime.now(UTC),
        summary_ro="Masa 1 așteaptă",
        snapshot=True,
    )
    await handler.handle(A.snapshot(event.event_id), b"\xff\xd8from-a")
    await handler.handle(B.snapshot(event.event_id), b"\xff\xd8from-b")
    await handler.handle(A.events, event.model_dump_json().encode())
    await handler.drain()

    assert notifier.snapshots == [b"\xff\xd8from-a"]
    async with sessions() as s:
        path = await s.scalar(
            text("SELECT snapshot_path FROM events WHERE event_id = :id"), {"id": event.event_id}
        )
    assert path == f"loc-a/edge-a/{event.event_id}.jpg"
    assert (tmp_path / path).read_bytes() == b"\xff\xd8from-a"


@pytest.mark.integration
async def test_a_snapshot_from_the_wrong_device_is_not_attached(
    sessions: Any, tmp_path: Path
) -> None:
    """Only device B sent an image for A's event id: A's alert goes out without one."""
    notifier = Recording()
    handler = _handler(tmp_path, sessions, notifier)
    event = AlertEvent(
        event_id=str(uuid.uuid4()),
        rule_id="r1",
        camera_id="cam1",
        zone_id="t1",
        state="opened",
        at=datetime.now(UTC),
        summary_ro="Masa 1 așteaptă",
        snapshot=True,
    )
    await handler.handle(B.snapshot(event.event_id), b"\xff\xd8from-b")
    await handler.handle(A.events, event.model_dump_json().encode())
    await handler.drain()
    assert notifier.snapshots == [None]
