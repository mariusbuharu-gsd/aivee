from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.alerts.audit import AuditWriter, acknowledged_entry
from aivee_api.alerts.auth import Access
from aivee_api.alerts.domain import Lifecycle, service_stats, wait_heatmap
from aivee_api.alerts.repository import AlertRepository
from aivee_api.alerts.schemas import (
    AlertView,
    HeatCellOut,
    ServiceHeatmap,
    ServiceMetrics,
    VerificationCount,
    VerificationMetrics,
)
from aivee_api.errors import Conflict, NotFound

DEFAULT_PERIOD = timedelta(days=1)
HEATMAP_PERIOD = timedelta(days=7)
# Locations have no timezone of their own yet; the venues are in Romania.
LOCATION_TZ = "Europe/Bucharest"
METRICS_MAX_ALERTS = 10_000
_MISSING = "Alerta nu există."


class AlreadyAcknowledged(Conflict):
    code = "already_acknowledged"


class AlertClosed(Conflict):
    code = "alert_closed"


def _now() -> datetime:
    return datetime.now(UTC)


async def acknowledge(
    session: AsyncSession,
    access: Access,
    event_id: str,
    audit: AuditWriter,
    location_id: str | None = None,
    now: Callable[[], datetime] = _now,
) -> AlertView:
    """ "Merg eu": the user takes the alert. 409 once someone has, or once it is closed."""
    repo = AlertRepository(session)
    alert_id = await repo.resolve(event_id)
    before = await repo.view(alert_id) if alert_id else None
    if (
        alert_id is None
        or before is None
        or not access.allows(before.location_id)
        or (location_id is not None and before.location_id != location_id)
    ):
        raise NotFound(_MISSING)
    if not await repo.acknowledge(alert_id, access.user, now()):
        if before.closed_at is not None:
            raise AlertClosed("Alerta s-a închis deja.")
        who = before.acknowledged_by or "altcineva"
        raise AlreadyAcknowledged(f"Alerta a fost deja preluată de {who}.")
    view = await repo.view(alert_id)
    assert view is not None
    await audit.append(session, acknowledged_entry(view, access.user))
    await session.commit()
    return view


def _locations(access: Access, location_id: str | None) -> list[str] | None:
    if location_id is not None:
        if not access.allows(location_id):
            raise NotFound("Locația nu există.")
        return [location_id]
    return None if access.locations is None else sorted(access.locations)


async def list_alerts(
    session: AsyncSession,
    access: Access,
    location_id: str | None,
    state: str | None,
    limit: int,
    before: datetime | None = None,
) -> list[AlertView]:
    """Newest first; `before` pages back (alerts opened strictly before it)."""
    return await AlertRepository(session).views(
        location_ids=_locations(access, location_id),
        state=state,
        opened_to=before,
        live_only=True,
        limit=limit,
    )


async def service_metrics(
    session: AsyncSession,
    access: Access,
    location_id: str | None,
    start: datetime | None,
    end: datetime | None,
    now: Callable[[], datetime] = _now,
) -> ServiceMetrics:
    """Median / p90 of wait, reaction and travel over the alerts opened in [from, to)."""
    end = end or now()
    start = start or end - DEFAULT_PERIOD
    views = await AlertRepository(session).views(
        location_ids=_locations(access, location_id),
        opened_from=start,
        opened_to=end,
        live_only=True,  # an uploaded clip is not service: no median / p90 from it
        limit=METRICS_MAX_ALERTS,
    )
    lives = [Lifecycle(v.opened_at, v.acknowledged_at, v.arrived_at, v.closed_at) for v in views]
    return ServiceMetrics.of(service_stats(lives), location_id, start, end)


async def service_heatmap(
    session: AsyncSession,
    access: Access,
    location_id: str | None,
    start: datetime | None,
    end: datetime | None,
    now: Callable[[], datetime] = _now,
) -> ServiceHeatmap:
    """Alerts opened in [from, to) and their median wait per local weekday x hour."""
    end = end or now()
    start = start or end - HEATMAP_PERIOD
    views = await AlertRepository(session).views(
        location_ids=_locations(access, location_id),
        opened_from=start,
        opened_to=end,
        live_only=True,
        limit=METRICS_MAX_ALERTS,
    )
    lives = [Lifecycle(v.opened_at, v.acknowledged_at, v.arrived_at, v.closed_at) for v in views]
    grid = wait_heatmap(lives, ZoneInfo(LOCATION_TZ))
    return ServiceHeatmap(
        location_id=location_id,
        from_=start,
        to=end,
        timezone=LOCATION_TZ,
        cells=[[HeatCellOut.of(c) for c in row] for row in grid],
    )


async def verification_metrics(
    session: AsyncSession, access: Access, location_id: str | None
) -> VerificationMetrics:
    counts = await AlertRepository(session).verification_counts(_locations(access, location_id))
    return VerificationMetrics(
        location_id=location_id,
        counts=[VerificationCount(rule_id=r, status=st, alerts=n) for r, st, n in counts],
    )
