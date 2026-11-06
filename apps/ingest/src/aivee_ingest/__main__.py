"""`python -m aivee_ingest`: MQTT → Postgres + snapshots + notifications."""

import asyncio
import contextlib
import logging
import signal

from aivee_api.alerts.audit import RepositoryAuditWriter
from aivee_api.db.session import make_engine, make_session_factory
from aivee_api.push.sender import WebPushSender
from aivee_api.push.settings import VapidSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_ingest.config import IngestSettings
from aivee_ingest.handler import IngestHandler
from aivee_ingest.locations import telegram_chat_for
from aivee_ingest.notify import LogNotifier, Notifier
from aivee_ingest.realert import Realerter, run_realerts
from aivee_ingest.telegram import TelegramNotifier
from aivee_ingest.verify import AlertVerification, DbVerificationStore, build_verifier
from aivee_ingest.webpush import CompositeNotifier, WebPushNotifier
from aivee_ingest.worker import run_worker

log = logging.getLogger("aivee_ingest")


def build_notifier(
    settings: IngestSettings,
    sessions: async_sessionmaker[AsyncSession] | None = None,
    vapid: VapidSettings | None = None,
) -> Notifier:
    notifiers: list[Notifier] = []
    if settings.telegram_bot_token and (settings.telegram_chat_id or sessions is not None):
        log.info("notifier: Telegram (location chat, else TELEGRAM_CHAT_ID)")

        async def chat_for(event_id: str) -> str | None:
            return await telegram_chat_for(sessions, event_id) if sessions is not None else None

        notifiers.append(
            TelegramNotifier(
                settings.telegram_bot_token,
                settings.telegram_chat_id,
                prefix=settings.telegram_prefix,
                chat_for=chat_for,
            )
        )
    else:
        log.info("notifier: log (TELEGRAM_BOT_TOKEN not set)")
        notifiers.append(LogNotifier())
    vapid = vapid or VapidSettings()
    if sessions is not None and vapid.enabled:
        log.info("notifier: Web Push")
        notifiers.append(WebPushNotifier(sessions, WebPushSender(vapid)))
    else:
        log.info("notifier: no Web Push (VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY not set)")
    return notifiers[0] if len(notifiers) == 1 else CompositeNotifier(notifiers)


async def main() -> None:
    settings = IngestSettings()
    engine = make_engine()
    sessions = make_session_factory(engine)
    notifier = build_notifier(settings, sessions)
    audit = RepositoryAuditWriter()
    verifier = build_verifier(settings)
    verification = (
        AlertVerification(
            verifier,
            DbVerificationStore(sessions),
            notifier,
            settings.snapshot_dir,
            timeout_s=settings.verify_timeout_s,
        )
        if verifier is not None
        else None
    )
    handler = IngestHandler(
        sessions, settings.snapshot_dir, notifier, audit=audit, verification=verification
    )
    realerter = Realerter(sessions, notifier, audit, settings.realert_after_s)

    async def run() -> None:
        await asyncio.gather(
            run_worker(settings, handler),
            run_realerts(realerter, settings.realert_interval_s),
        )

    task = asyncio.create_task(run())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await engine.dispose()
    log.info("ingest stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # httpx logs full request URLs at INFO, and the Telegram URL contains the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(main())
