"""Notifier port and the Romanian alert text shared by all notifiers."""

import logging
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from aivee_api.push.sender import PushKind
from aivee_contracts.events import AlertEvent

log = logging.getLogger(__name__)

# Venues are in Romania; containers run in UTC.
LOCAL_TZ = ZoneInfo("Europe/Bucharest")


class Notifier(Protocol):
    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        """Tell the staff about a newly opened event. `snapshot` is a blurred JPEG."""
        ...

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None, kind: PushKind
    ) -> None:
        """A follow-up message, e.g. "Un angajat a ajuns la Masa 4 după 2 min 10 s ·
        preluată de Ana". `tag` is the alert's id (Web Push uses it to replace the alert's
        notification); `title` is the push title where the channel has one; `kind` tells
        the dashboard's service worker whether the replaced notification rings again."""
        ...


def with_prefix(prefix: str, text: str) -> str:
    return f"{prefix} {text}" if prefix else text


def alert_text(event: AlertEvent, prefix: str = "") -> str:
    when = event.at.astimezone(LOCAL_TZ).strftime("%H:%M")
    return with_prefix(
        prefix,
        f"Alertă AiVee: {event.summary_ro}\n"
        f"Camera: {event.camera_id} · Zona: {event.zone_id} · Ora: {when}",
    )


class LogNotifier:
    """Fallback when Telegram is not configured: write the alert to the log."""

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        log.info(
            "ALERT %s (snapshot: %s)",
            alert_text(event).replace("\n", " | "),
            snapshot.name if snapshot else "none",
        )

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None, kind: PushKind
    ) -> None:
        log.info("ALERT %s (alert: %s)", text, tag)
