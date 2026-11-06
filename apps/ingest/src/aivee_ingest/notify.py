"""Notifier port and the Romanian alert text shared by all notifiers."""

import logging
from pathlib import Path
from typing import Protocol

from aivee_contracts.events import AlertEvent

log = logging.getLogger(__name__)


class Notifier(Protocol):
    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        """Tell the staff about a newly opened event. `snapshot` is a blurred JPEG."""
        ...


def alert_text(event: AlertEvent) -> str:
    when = event.at.astimezone().strftime("%H:%M")
    return (
        f"Alertă AiVee: {event.summary_ro}\n"
        f"Camera: {event.camera_id} · Zona: {event.zone_id} · Ora: {when}"
    )


class LogNotifier:
    """Fallback when Telegram is not configured: write the alert to the log."""

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        log.info(
            "ALERT %s (snapshot: %s)",
            alert_text(event).replace("\n", " | "),
            snapshot.name if snapshot else "none",
        )
