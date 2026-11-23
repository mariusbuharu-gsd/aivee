"""Turn one MQTT message from an edge device into rows, files and notifications."""

import logging
import os
import uuid
from collections import deque
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from aivee_api.alerts.audit import (
    AuditWriter,
    LoggingAuditWriter,
    device_entry,
    system_closed_entry,
)
from aivee_api.alerts.domain import device_closed_note_ro, system_close_reason
from aivee_api.alerts.repository import AlertRepository
from aivee_api.alerts.schemas import AlertView
from aivee_api.audit.repository import Actor, AuditRepository, Target
from aivee_api.db.models import Device, Site
from aivee_api.db.repositories import DeviceRepository, EventRepository, SuggestionRepository
from aivee_api.events.service import snapshot_key
from aivee_api.videos.kind import is_upload, is_upload_device
from aivee_contracts.events import AlertEvent, DeviceStatus, StaffSuggestion, before_snapshot_id
from aivee_contracts.topics import ROOT, Topics
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_ingest.dispatch import NotifyDispatcher
from aivee_ingest.lifecycle import (
    arrived_ro,
    closed_line,
    is_guest_rule,
    left_ro,
    resolved_line,
)
from aivee_ingest.locations import rule_conditions
from aivee_ingest.notify import LifecycleNotifier, Notifier
from aivee_ingest.verify import UNAVAILABLE, AlertVerification, wait_for_file

log = logging.getLogger(__name__)

LEFT_TITLE = "AiVee · Client plecat"
SYSTEM_CLOSED_LINE = {
    "device_offline": "⚪ Închisă · dispozitivul s-a deconectat",
    "device_restarted": "⚪ Închisă · dispozitivul a repornit",
}


class IngestHandler:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        snapshot_dir: Path,
        notifier: Notifier,
        snapshot_wait_s: float = 2.0,
        audit: AuditWriter | None = None,
        verification: AlertVerification | None = None,
        close_grace_s: float = 3.0,
        dispatcher: NotifyDispatcher | None = None,
    ) -> None:
        self._close_grace_s = close_grace_s
        # Everything that talks to the staff runs here, never on the MQTT loop (R3).
        self._dispatch = dispatcher or NotifyDispatcher()
        self._sessions = sessions
        self._audit = audit or LoggingAuditWriter()
        self._snapshots = snapshot_dir
        self._notifier = notifier
        self._snapshot_wait_s = snapshot_wait_s
        self._verification = verification
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
                self._on_snapshot(t, topic.removeprefix(t.snapshot("")), payload)
        except ValidationError as e:
            log.warning("invalid payload on %s: %s", topic, e.errors()[:3])

    async def _on_event(self, t: Topics, event: AlertEvent) -> None:
        self.handled_events.append(event.event_id)
        # An uploaded clip is stored and folded like any alert, but it must never ring the
        # staff's phones, and its alerts stay out of the history.
        upload = is_upload(t.device, event.camera_id)
        # The images this event's own device sent (S4): `<site>/<device>/<id>.jpg`.
        path = snapshot_key(t.site, t.device, event.event_id) if event.snapshot else None
        change = event.object_change
        before = (
            snapshot_key(t.site, t.device, before_snapshot_id(event.event_id))
            if change is not None and change.before_snapshot
            else None
        )
        view: AlertView | None = None
        early: list[str] = []
        async with self._sessions() as s:
            inserted = await EventRepository(s).insert_if_new(event, t.device, path, before)
            if inserted:
                # Same transaction: the row, its alert's folded times and the audit entry.
                alerts = AlertRepository(s)
                alert_id, folded = await alerts.link_folded(event, t.device)
                if event.state == "opened":
                    # Its `arrived` / `closed` may have come first (R2): fold them now.
                    early = await alerts.adopt_early(event, t.device)
                if event.state == "opened" and self._verification is None:
                    await alerts.save_verification(event.event_id, UNAVAILABLE, datetime.now(UTC))
                view = await alerts.view(alert_id) if alert_id and folded else None
                if view is not None and not upload:
                    for state in [event.state, *early]:
                        entry = device_entry(view, state)
                        if entry is not None:
                            await self._audit.append(s, entry)
            await s.commit()
        if not inserted:
            log.info("duplicate event %s ignored", event.event_id)
            return
        if upload:
            log.info(
                "clip event %s %s camera=%s (uploaded clip: nobody notified)",
                event.event_id,
                event.state,
                event.camera_id,
            )
            return
        log.info(
            "event %s %s rule=%s camera=%s zone=%s",
            event.event_id,
            event.state,
            event.rule_id,
            event.camera_id,
            event.zone_id,
        )
        if early:
            # It ended before it reached us: nothing left for the staff to do.
            log.info(
                "notify_skipped reason=already_%s alert=%s",
                "closed" if "closed" in early else "arrived",
                event.event_id,
            )
            return
        # Queued per alert (the opened event's id), so its jobs keep their order.
        if event.state == "opened" and self._verification is not None:
            folder = f"{t.site}/{t.device}"
            self._dispatch.submit(event.event_id, "verify", lambda: self._verify(event, folder))
        elif event.state == "opened":
            self._dispatch.submit(
                event.event_id, "opened", lambda: self._notify_opened(event, path)
            )
        elif event.state == "arrived" and view is not None:
            arrived = view
            self._dispatch.submit(arrived.event_id, "arrived", lambda: self._arrived(arrived))
        elif event.state == "closed" and view is not None and view.arrived_at is None:
            # After a grace: the `arrived` may still be on its way (another replica).
            alert_id = view.event_id
            self._dispatch.submit_later(
                self._close_grace_s, alert_id, "closed", lambda: self._closed_unserved(alert_id)
            )

    async def _notify_opened(self, event: AlertEvent, path: str | None) -> None:
        snapshot = await self._wait_snapshot(path) if path else None
        try:
            await self._notifier.notify(event, snapshot)
        except Exception:
            log.exception("notifier failed for event %s", event.event_id)

    async def _arrived(self, view: AlertView) -> None:
        try:
            await self._notifier.send_text(arrived_ro(view), view.event_id, kind="arrived")
        except Exception:
            log.exception("notifier failed for the arrival of %s", view.event_id)
        await self._resolved(view, resolved_line(view))

    async def _closed_unserved(self, alert_id: str) -> None:
        """Nobody arrived and the situation ended: for a table, the guest left unserved.
        Runs `close_grace_s` after the close, so an `arrived` processed late is not mistaken
        for it."""
        try:
            async with self._sessions() as s:
                view = await AlertRepository(s).view(alert_id)
            if view is None or view.arrived_at is not None:
                return
            guest = is_guest_rule(await rule_conditions(self._sessions, view.rule_id))
            try:
                await self._notifier.send_text(
                    left_ro(view, guest=guest), view.event_id, title=LEFT_TITLE, kind="arrived"
                )
            except Exception:
                log.exception("notifier failed for the close of %s", alert_id)
            await self._resolved(view, closed_line(guest=guest))
        except Exception:
            log.exception("close follow-up of %s failed", alert_id)

    async def _resolved(self, view: AlertView, line: str) -> None:
        """Edit the original alert (Telegram): how it ended, no buttons."""
        if not isinstance(self._notifier, LifecycleNotifier):
            return
        try:
            await self._notifier.alert_resolved(view, line)
        except Exception:
            log.exception("could not mark alert %s as resolved", view.event_id)

    async def _verify(self, event: AlertEvent, folder: str) -> None:
        assert self._verification is not None
        try:
            await self._verification.run(event, folder)
        except Exception:
            log.exception("verification task failed for event %s", event.event_id)

    async def drain(self) -> None:
        """Wait for the notifications queued or in flight (tests, shutdown)."""
        await self._dispatch.drain()

    async def aclose(self) -> None:
        await self._dispatch.aclose()

    async def _wait_snapshot(self, name: str) -> Path | None:
        return await wait_for_file(self._snapshots / name, self._snapshot_wait_s)

    async def _on_status(self, t: Topics, status: DeviceStatus) -> None:
        # The topic (enforced by the broker ACL) is the source of truth for the device id.
        status = status.model_copy(update={"device": t.device})
        if is_upload_device(t.device):
            # The clip runner goes offline at the end of every clip: no history entry, no
            # note to the staff, and the API closes the clip's alerts itself (video_end).
            async with self._sessions() as s:
                await DeviceRepository(s).apply_status(t.site, status)
                await s.commit()
            return
        closed: list[AlertView] = []
        async with self._sessions() as s:
            # Every replica gets every status: serialise per device so a change is audited
            # once, and its open alerts are closed (and announced) once.
            await s.execute(select(func.pg_advisory_xact_lock(func.hashtext(t.device))))
            devices = DeviceRepository(s)
            before = await s.scalar(select(Device.state).where(Device.id == t.device))
            await devices.apply_status(t.site, status)
            if before != status.state:
                site = await s.get(Site, t.site)
                await AuditRepository(s).append(
                    f"device.{status.state}",
                    Actor("device", t.device, t.device),
                    org_id=site.org_id if site else None,
                    location_id=t.site,
                    target=Target("device", t.device, t.device),
                    before={"state": before} if before else None,
                    after={"state": status.state},
                )
            reason = system_close_reason(before, status.state)
            if reason is not None:
                closed = await AlertRepository(s).close_open_for_device(
                    t.device, datetime.now(UTC), reason
                )
                for view in closed:
                    await self._audit.append(s, system_closed_entry(view, reason))
            await s.commit()
        log.info("device %s/%s is %s", t.site, t.device, status.state)
        if closed and reason is not None:
            log.info("closed %d open alert(s) of %s: %s", len(closed), t.device, reason)
            note = device_closed_note_ro(t.device, reason, len(closed))
            tag = closed[0].event_id
            self._dispatch.submit(tag, "device", lambda: self._device_note(note, tag, t.device))
            line = SYSTEM_CLOSED_LINE.get(reason, "⚪ Închisă")
            for view in closed:
                self._dispatch.submit(
                    view.event_id, "resolved", partial(self._resolved, view, line)
                )

    async def _device_note(self, note: str, tag: str, device: str) -> None:
        try:
            # No "a ajuns": nobody came. The tag picks the location (and its chat).
            await self._notifier.send_text(note, tag, title="AiVee · Dispozitiv", kind="device")
        except Exception:
            log.exception("notifier failed for the device note of %s", device)

    async def _on_suggestion(self, t: Topics, suggestion: StaffSuggestion) -> None:
        async with self._sessions() as s:
            path = snapshot_key(t.site, t.device, suggestion.suggestion_id)
            await SuggestionRepository(s).insert_if_new(suggestion, t.device, path)
            await s.commit()

    async def _on_metrics(self, t: Topics) -> None:
        async with self._sessions() as s:
            await DeviceRepository(s).touch(t.device)
            await s.commit()

    def _on_snapshot(self, t: Topics, snapshot_id: str, payload: bytes) -> None:
        key = snapshot_key(t.site, t.device, snapshot_id)
        if key is None:
            log.warning("ignoring snapshot with unsafe topic %r", t.snapshot(snapshot_id))
            return
        final = self._snapshots / key
        final.parent.mkdir(parents=True, exist_ok=True)
        # Replicas share the dir and may all be pid 1: the temp name must be unique per write.
        tmp = final.with_suffix(f".{uuid.uuid4().hex}.tmp")
        tmp.write_bytes(payload)
        os.replace(tmp, final)  # atomic: every worker writes the same bytes
