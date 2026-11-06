"""Everything a request needs, wired once per app and reached through FastAPI dependencies."""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Protocol

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_api.auth.ratelimit import LoginRateLimiter
from aivee_api.edge.live import LiveDetections
from aivee_api.edge.sync import EdgeCommands, EdgeSync
from aivee_api.frames.store import LiveFrames
from aivee_api.locations.telegram import BotUsername
from aivee_api.metrics.cache import MetricsCache
from aivee_api.rules.translator import RuleTranslator
from aivee_api.settings import ApiSettings
from aivee_api.staff.capture import CaptureStore
from aivee_api.staff.enrol import Enroller
from aivee_api.videos.probe import probe_duration


class VideoJobs(Protocol):
    def submit(self, upload_id: str) -> None: ...


@dataclass
class Services:
    settings: ApiSettings
    sessions: async_sessionmaker[AsyncSession]
    sync: EdgeSync
    translator: RuleTranslator
    commands: EdgeCommands
    enroller: Enroller | None = None
    metrics: MetricsCache = field(default_factory=MetricsCache)
    live: LiveDetections = field(default_factory=LiveDetections)
    frames: LiveFrames = field(default_factory=LiveFrames)
    """Cloud mode: newest JPEG per camera posted over HTTPS (in memory, single replica)."""
    captures: CaptureStore = field(default_factory=CaptureStore)
    """Guided staff captures awaiting confirmation (in memory, single replica)."""
    login_limiter: LoginRateLimiter = field(default_factory=LoginRateLimiter)
    videos: VideoJobs | None = None
    """Queue of uploaded clips to analyse (None: Analiză video is off)."""
    video_probe: Callable[[Path], float | None] = probe_duration
    telegram_bot: BotUsername | None = None
    """The bot's @username for "Conectează Telegram" links (None: the feature answers 503)."""


def get_services(request: Request) -> Services:
    svc: Services = request.app.state.services
    return svc


async def get_session(
    svc: Annotated[Services, Depends(get_services)],
) -> AsyncIterator[AsyncSession]:
    async with svc.sessions() as s:
        yield s


ServicesDep = Annotated[Services, Depends(get_services)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
