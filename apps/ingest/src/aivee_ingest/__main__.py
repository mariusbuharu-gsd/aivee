"""`python -m aivee_ingest`: MQTT → Postgres + snapshots + notifications."""

import asyncio
import contextlib
import logging
import signal

from aivee_api.db.session import make_engine, make_session_factory

from aivee_ingest.config import IngestSettings
from aivee_ingest.handler import IngestHandler
from aivee_ingest.notify import LogNotifier, Notifier
from aivee_ingest.telegram import TelegramNotifier
from aivee_ingest.worker import run_worker

log = logging.getLogger("aivee_ingest")


def build_notifier(settings: IngestSettings) -> Notifier:
    if settings.telegram_bot_token and settings.telegram_chat_id:
        log.info("notifier: Telegram")
        return TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    log.info("notifier: log (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set)")
    return LogNotifier()


async def main() -> None:
    settings = IngestSettings()
    engine = make_engine()
    handler = IngestHandler(
        make_session_factory(engine), settings.snapshot_dir, build_notifier(settings)
    )
    task = asyncio.create_task(run_worker(settings, handler))
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
