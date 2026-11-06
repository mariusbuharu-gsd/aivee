"""Web Push notifier (the dashboard PWA on waiters' phones) and the composite notifier.

An opened alert and its follow-ups go to the subscriptions of the members (and owners) of
the alert's location; an alert without a location reaches nobody. Expired subscriptions
(404/410 from the push service) are dropped by `push_to`.
"""

import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path

from aivee_api.alerts.schemas import AlertView
from aivee_api.db.repositories import CameraRepository
from aivee_api.push.sender import PushKind, PushMessage, PushSender
from aivee_api.push.service import push_to_location
from aivee_contracts.events import AlertEvent
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_ingest.locations import alert_location
from aivee_ingest.notify import REMINDER_TITLE, LifecycleNotifier, Notifier

log = logging.getLogger(__name__)


class WebPushNotifier:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], sender: PushSender) -> None:
        self._sessions = sessions
        self._sender = sender

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        location_id = await alert_location(self._sessions, event.event_id)
        if location_id is None:
            log.warning("no location for alert %s; push not sent", event.event_id)
            return
        zone = await self._zone_name(event.camera_id, event.zone_id)
        message = PushMessage(
            title=f"Alertă AiVee · {zone}",
            body=event.summary_ro,
            kind="alert",
            url="/alerte",
            tag=event.event_id,
        )
        await push_to_location(self._sessions, self._sender, message, location_id)

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None, kind: PushKind
    ) -> None:
        """Follow-up (staff arrived, device gone); the same `tag` replaces the alert's
        notification. `title` defaults to the arrival's."""
        location_id = await alert_location(self._sessions, tag) if tag else None
        if location_id is None:
            log.warning("no location for alert %s; follow-up push not sent", tag)
            return
        message = PushMessage(
            title=title or "AiVee · Angajat sosit",
            body=text,
            kind=kind,
            url="/alerte",
            tag=tag or "aivee",
        )
        await push_to_location(self._sessions, self._sender, message, location_id)

    async def alert_resolved(self, view: AlertView, line: str) -> None:
        """Nothing to edit: the follow-up (same tag) already replaced the notification."""

    async def alert_reminder(self, view: AlertView, text: str) -> None:
        await self.send_text(text, view.event_id, title=REMINDER_TITLE, kind="realert")

    async def _zone_name(self, camera_id: str, zone_id: str) -> str:
        async with self._sessions() as s:
            camera = await CameraRepository(s).get(camera_id)
        for zone in camera.zones if camera else []:
            if zone.get("id") == zone_id and zone.get("name"):
                return str(zone["name"])
        return zone_id


class CompositeNotifier:
    """Fan one alert out to several notifiers; one failing never stops the others."""

    def __init__(self, notifiers: Sequence[Notifier]) -> None:
        self.notifiers = list(notifiers)

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        results = await asyncio.gather(
            *(n.notify(event, snapshot) for n in self.notifiers), return_exceptions=True
        )
        self._log_failures(results, f"event {event.event_id}")

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None, kind: PushKind
    ) -> None:
        results = await asyncio.gather(
            *(n.send_text(text, tag, title=title, kind=kind) for n in self.notifiers),
            return_exceptions=True,
        )
        self._log_failures(results, f"follow-up {tag}")

    async def alert_resolved(self, view: AlertView, line: str) -> None:
        targets = [n for n in self.notifiers if isinstance(n, LifecycleNotifier)]
        results = await asyncio.gather(
            *(n.alert_resolved(view, line) for n in targets), return_exceptions=True
        )
        self._log_failures(results, f"resolved {view.event_id}", targets)

    async def alert_reminder(self, view: AlertView, text: str) -> None:
        targets = [n for n in self.notifiers if isinstance(n, LifecycleNotifier)]
        results = await asyncio.gather(
            *(n.alert_reminder(view, text) for n in targets), return_exceptions=True
        )
        self._log_failures(results, f"reminder {view.event_id}", targets)

    def _log_failures(
        self, results: Sequence[object], what: str, notifiers: Sequence[object] | None = None
    ) -> None:
        targets = self.notifiers if notifiers is None else notifiers
        for notifier, result in zip(targets, results, strict=True):
            if isinstance(result, BaseException):
                log.error("%s failed for %s: %s", type(notifier).__name__, what, result)
