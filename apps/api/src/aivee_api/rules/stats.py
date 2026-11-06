"""Alerts per rule per day (the Reguli cards' sparkline). An alert is an `opened` event;
uploaded clips' rules and alerts never count."""

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.auth.scope import cameras_at
from aivee_api.db.models import EventRow, RuleRow
from aivee_api.rules.schemas import RuleAlertCount, RuleStats
from aivee_api.videos.kind import is_upload_camera, not_upload


def stat_days(today: date, days: int) -> list[date]:
    """The `days` days ending with `today`, oldest first."""
    return [today - timedelta(days=days - 1 - i) for i in range(days)]


async def rule_stats(s: AsyncSession, location_id: str, days: int, today: date) -> RuleStats:
    window = stat_days(today, days)
    start = datetime.combine(window[0], time(), tzinfo=UTC)
    rules = (
        await s.execute(
            select(RuleRow.id, RuleRow.camera_id)
            .where(RuleRow.camera_id.in_(cameras_at(location_id)))
            .order_by(RuleRow.id)
        )
    ).all()
    ids = [rule_id for rule_id, camera_id in rules if not is_upload_camera(camera_id)]
    day = cast(func.timezone("UTC", EventRow.at), Date)
    rows = (
        await s.execute(
            select(EventRow.rule_id, day, func.count())
            .where(
                EventRow.state == "opened",
                EventRow.at >= start,
                EventRow.rule_id.in_(ids),
                EventRow.camera_id.in_(cameras_at(location_id)),
                not_upload(EventRow.device_id, EventRow.camera_id),
            )
            .group_by(EventRow.rule_id, day)
        )
    ).all()
    counts: dict[tuple[str, date], int] = {(r, d): n for r, d, n in rows}
    out = []
    for rule_id in ids:
        per_day = [counts.get((rule_id, d), 0) for d in window]
        out.append(RuleAlertCount(rule_id=rule_id, total=sum(per_day), per_day=per_day))
    return RuleStats(days=window, rules=out)
