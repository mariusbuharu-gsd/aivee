"""R3: a notifier that hangs never delays storing the next events."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from aivee_api.push.sender import PushKind
from aivee_contracts.events import AlertEvent
from aivee_contracts.topics import Topics
from aivee_ingest.handler import IngestHandler
from sqlalchemy import text

pytestmark = pytest.mark.integration

T = Topics(site="loc-r3", device="edge-r3")


class Hanging:
    """Every send blocks until released; records what was sent, in order."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.sent: list[str] = []

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        await self.release.wait()
        self.sent.append(f"opened:{event.event_id}")

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None, kind: PushKind
    ) -> None:
        await self.release.wait()
        self.sent.append(f"{kind}:{tag}")


def _event(state: str = "opened", **kw: Any) -> AlertEvent:
    data: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "rule_id": "r1",
        "camera_id": "cam1",
        "zone_id": f"t-{uuid.uuid4().hex[:6]}",
        "state": state,
        "at": datetime.now(UTC),
        "summary_ro": "Masa 1 așteaptă",
    }
    return AlertEvent.model_validate({**data, **kw})


async def _count(sessions: Any) -> int:
    async with sessions() as s:
        return int(await s.scalar(text("SELECT count(*) FROM events")) or 0)


async def test_a_hanging_notifier_does_not_delay_event_persistence(
    sessions: Any, tmp_path: Path
) -> None:
    notifier = Hanging()
    handler = IngestHandler(sessions, tmp_path, notifier, close_grace_s=0)
    first = _event(snapshot=True)  # its snapshot never comes: the wait is off the loop too
    arrived = first.model_copy(
        update={
            "event_id": str(uuid.uuid4()),
            "state": "arrived",
            "at": first.at + timedelta(seconds=30),
        }
    )
    others = [_event() for _ in range(5)]

    async def handle_all() -> None:
        for e in [first, arrived, *others]:
            await handler.handle(T.events, e.model_dump_json().encode())

    await asyncio.wait_for(handle_all(), timeout=3)  # inline, this would hang forever
    assert await _count(sessions) == 7
    assert notifier.sent == []

    notifier.release.set()
    await asyncio.wait_for(handler.drain(), timeout=10)
    # Per alert, in order: the alert before its "arrived".
    assert notifier.sent.index(f"opened:{first.event_id}") < notifier.sent.index(
        f"arrived:{first.event_id}"
    )
    assert {f"opened:{e.event_id}" for e in others} <= set(notifier.sent)
    await handler.aclose()
