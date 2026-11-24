"""`python -m aivee_ingest`: MQTT → Postgres + snapshots + notifications."""

import asyncio
import contextlib
import logging
import signal

from aivee_api.alerts.audit import RepositoryAuditWriter
from aivee_api.db.session import make_engine, make_session_factory
from aivee_api.push.sender import WebPushSender
from aivee_api.push.settings import VapidSettings
from aivee_contracts.events import AlertEvent
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_ingest.alert_message import AlertContext
from aivee_ingest.config import IngestSettings
from aivee_ingest.dispatch import NotifyDispatcher, RetryingNotifier
from aivee_ingest.handler import IngestHandler
from aivee_ingest.locations import alert_context, telegram_chat_for
from aivee_ingest.notify import LogNotifier, Notifier
from aivee_ingest.realert import Realerter, run_realerts
from aivee_ingest.remind import Reminder, run_reminders
from aivee_ingest.sent import DbSentMessages
from aivee_ingest.telegram import ContextLookup, TelegramNotifier
from aivee_ingest.telegram_ack import AlertCallbacks, DbAckStore
from aivee_ingest.telegram_link import (
    AdvisoryPollLock,
    DbLinkStore,
    HttpBotApi,
    TelegramLinkBot,
    run_link_poller,
)
from aivee_ingest.verify import AlertVerification, DbVerificationStore, build_verifier
from aivee_ingest.webpush import CompositeNotifier, WebPushNotifier
from aivee_ingest.worker import run_worker

log = logging.getLogger("aivee_ingest")


def retrying(channel: Notifier, settings: IngestSettings) -> Notifier:
    """A channel that retries a failed send itself, so the others are not sent twice."""
    return RetryingNotifier(channel, attempts=settings.notify_attempts)


def build_notifier(
    settings: IngestSettings,
    sessions: async_sessionmaker[AsyncSession] | None = None,
    vapid: VapidSettings | None = None,
) -> Notifier:
    notifiers: list[Notifier] = []
    if settings.telegram_chat_id and not settings.telegram_single_tenant:
        log.warning("TELEGRAM_CHAT_ID ignored: set TELEGRAM_SINGLE_TENANT=true to use it")
    fallback = settings.telegram_fallback_chat
    if settings.telegram_bot_token and (fallback or sessions is not None):
        log.info(
            "notifier: Telegram (the location's chat%s)",
            ", else TELEGRAM_CHAT_ID" if fallback else "; none: not sent",
        )

        async def chat_for(event_id: str) -> str | None:
            return await telegram_chat_for(sessions, event_id) if sessions is not None else None

        context_for: ContextLookup | None = None
        if sessions is not None:
            db = sessions

            async def names_for(event: AlertEvent) -> AlertContext:
                return await alert_context(db, event)

            context_for = names_for

        notifiers.append(
            retrying(
                TelegramNotifier(
                    settings.telegram_bot_token,
                    fallback,
                    prefix=settings.telegram_prefix,
                    chat_for=chat_for,
                    context_for=context_for,
                    dashboard_url=settings.public_dashboard_url,
                    sent=DbSentMessages(sessions) if sessions is not None else None,
                ),
                settings,
            )
        )
    else:
        log.info("notifier: log (TELEGRAM_BOT_TOKEN not set)")
        notifiers.append(LogNotifier())
    vapid = vapid or VapidSettings()
    if sessions is not None and vapid.enabled:
        log.info("notifier: Web Push")
        notifiers.append(retrying(WebPushNotifier(sessions, WebPushSender(vapid)), settings))
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
        sessions,
        settings.snapshot_dir,
        notifier,
        audit=audit,
        verification=verification,
        dispatcher=NotifyDispatcher(settings.notify_workers, settings.notify_queue_size),
    )
    realerter = Realerter(sessions, notifier, audit, settings.realert_after_s)

    jobs = [run_worker(settings, handler), run_realerts(realerter, settings.realert_interval_s)]
    if settings.remind_s > 0:
        reminder = Reminder(sessions, notifier, settings.remind_s)
        jobs.append(run_reminders(reminder, settings.realert_interval_s))
    else:
        log.info("alert reminders off (REMIND_S=0)")
    if settings.telegram_bot_token and settings.telegram_poll:
        bot_api = HttpBotApi(settings.telegram_bot_token)
        callbacks = AlertCallbacks(
            bot_api,
            DbAckStore(sessions, audit, settings.telegram_fallback_chat),
            prefix=settings.telegram_prefix,
            dashboard_url=settings.public_dashboard_url,
        )
        bot = TelegramLinkBot(bot_api, DbLinkStore(sessions), callbacks)
        jobs.append(run_link_poller(bot, bot_api, AdvisoryPollLock(engine)))
    else:
        log.info("Telegram link poller off (no TELEGRAM_BOT_TOKEN, or TELEGRAM_POLL=false)")

    async def run() -> None:
        await asyncio.gather(*jobs)

    task = asyncio.create_task(run())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    with contextlib.suppress(asyncio.CancelledError):
        await task
    # Best effort: send what is already queued, briefly (no outbox yet, R1).
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(handler.drain(), timeout=5)
    await handler.aclose()
    await engine.dispose()
    log.info("ingest stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # httpx logs full request URLs at INFO, and the Telegram URL contains the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(main())
