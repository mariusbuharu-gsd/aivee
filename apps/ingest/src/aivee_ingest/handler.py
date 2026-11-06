"""Turn one MQTT message from an edge device into rows, files and notifications."""

import asyncio
import logging
import os
import re
import uuid
from collections import deque
from pathlib import Path

from aivee_api.alerts.audit import AuditWriter, LoggingAuditWriter, arrival_ro, device_entry
from aivee_api.alerts.repository import AlertRepository
from aivee_api.alerts.schemas import AlertView
from aivee_api.db.repositories import DeviceRepository, EventRepository, SuggestionRepository
from aivee_contracts.events import AlertEvent, DeviceStatus, StaffSuggestion
from aivee_contracts.topics import ROOT, Topics
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_ingest.notify import Notifier

log = logging.getLogger(__name__)

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def snapshot_name(event_id: str) -> str:
    return f"{event_id}.jpg"


class IngestHandler:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        snapshot_dir: Path,
        notifier: Notifier,
        snapshot_wait_s: float = 2.0,
        audit: AuditWriter | None = None,
    ) -> None:
        self._sessions = sessions
        self._audit = audit or LoggingAuditWriter()
        self._snapshots = snapshot_dir
        self._notifier = notifier
        self._snapshot_wait_s = snapshot_wait_s
        self.handled_events: deque[str] = deque(maxlen=10_000)
        snapshot_dir.mkdir(parents=True, exist_ok=True)

    async def handle(self, topic: str, payload: bytes) -> None:
        parts = topic.split("/")
        if len(parts) < 4 or parts[0] != ROOT:
            log.warning("ignoring message on unexpected topic %s", topic)
            return
        t = Topics(site=parts[1], device=parts[2])
        try:
            if topic == t.events:
                await self._on_event(t, AlertEvent.model_validate_json(payload))
            elif topic == t.status:
                await self._on_status(t, DeviceStatus.model_validate_json(payload))
            elif topic == t.suggestions:
                await self._on_suggestion(t, StaffSuggestion.model_validate_json(payload))
            elif topic == t.metrics:
                await self._on_metrics(t)
            elif topic.startswith(t.snapshot("")):
                self._on_snapshot(topic.removeprefix(t.snapshot("")), payload)
        except ValidationError as e:
            log.warning("invalid payload on %s: %s", topic, e.errors()[:3])

    async def _on_event(self, t: Topics, event: AlertEvent) -> None:
        self.handled_events.append(event.event_id)
        path = snapshot_name(event.event_id) if event.snapshot else None
        view: AlertView | None = None
        async with self._sessions() as s:
            inserted = await EventRepository(s).insert_if_new(event, t.device, path)
            if inserted:
                # Same transaction: the row, its alert's folded times and the audit entry.
                alerts = AlertRepository(s)
                alert_id = await alerts.link(event, t.device)
                view = await alerts.view(alert_id) if alert_id else None
                entry = device_entry(view, event.state) if view else None
                if entry is not None:
                    await self._audit.append(s, entry)
            await s.commit()
        if not inserted:
            log.info("duplicate event %s ignored", event.event_id)
            return
        log.info(
            "event %s %s rule=%s camera=%s zone=%s",
            event.event_id,
            event.state,
            event.rule_id,
            event.camera_id,
            event.zone_id,
        )
        if event.state == "opened":
            snapshot = await self._wait_snapshot(path) if path else None
            try:
                await self._notifier.notify(event, snapshot)
            except Exception:
                log.exception("notifier failed for event %s", event.event_id)
        elif event.state == "arrived" and view is not None:
            try:
                await self._notifier.send_text(arrival_ro(view), view.event_id)
            except Exception:
                log.exception("notifier failed for event %s", event.event_id)

    async def _wait_snapshot(self, name: str) -> Path | None:
        file = self._snapshots / name
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._snapshot_wait_s
        while not file.is_file():
            if loop.time() >= deadline:
                log.warning("snapshot %s did not arrive in time", name)
                return None
            await asyncio.sleep(0.1)
        return file

    async def _on_status(self, t: Topics, status: DeviceStatus) -> None:
        # The topic (enforced by the broker ACL) is the source of truth for the device id.
        status = status.model_copy(update={"device": t.device})
        async with self._sessions() as s:
            await DeviceRepository(s).apply_status(t.site, status)
            await s.commit()
        log.info("device %s/%s is %s", t.site, t.device, status.state)

    async def _on_suggestion(self, t: Topics, suggestion: StaffSuggestion) -> None:
        async with self._sessions() as s:
            await SuggestionRepository(s).insert_if_new(suggestion, t.device)
            await s.commit()

    async def _on_metrics(self, t: Topics) -> None:
        async with self._sessions() as s:
            await DeviceRepository(s).touch(t.device)
            await s.commit()

    def _on_snapshot(self, event_id: str, payload: bytes) -> None:
        if not _SAFE_ID.match(event_id):
            log.warning("ignoring snapshot with unsafe id %r", event_id)
            return
        final = self._snapshots / snapshot_name(event_id)
        # Replicas share the dir and may all be pid 1: the temp name must be unique per write.
        tmp = final.with_suffix(f".{uuid.uuid4().hex}.tmp")
        tmp.write_bytes(payload)
        os.replace(tmp, final)  # atomic: every worker writes the same bytes
