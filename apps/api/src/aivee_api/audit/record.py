"""Record a user's action in the history (used by routers after a change is saved)."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.audit.repository import AuditRepository, Target
from aivee_api.auth.principal import Principal


async def record(
    s: AsyncSession,
    p: Principal,
    kind: str,
    *,
    location_id: str | None,
    target: Target | None = None,
    before: Any = None,
    after: Any = None,
    **fields: str,
) -> None:
    await AuditRepository(s).append(
        kind,
        p.actor,
        org_id=p.org_id,
        location_id=location_id,
        target=target,
        before=before,
        after=after,
        **fields,
    )
    await s.commit()
