"""Everything a request needs, wired once per app and reached through FastAPI dependencies."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_api.edge.sync import EdgeCommands, EdgeSync
from aivee_api.metrics.cache import MetricsCache
from aivee_api.rules.translator import RuleTranslator
from aivee_api.settings import ApiSettings
from aivee_api.staff.enrol import Enroller


@dataclass
class Services:
    settings: ApiSettings
    sessions: async_sessionmaker[AsyncSession]
    sync: EdgeSync
    translator: RuleTranslator
    commands: EdgeCommands
    enroller: Enroller | None = None
    metrics: MetricsCache = field(default_factory=MetricsCache)


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
