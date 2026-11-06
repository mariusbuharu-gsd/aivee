"""Which location an alert belongs to, and that location's Telegram chat.

Keyed by the alert's event id (stored before any notifier runs): the producing device's
location, else its camera's. The notifiers keep the plain Notifier port this way.
"""

from aivee_api.alerts.repository import AlertRepository
from aivee_api.auth.scope import event_location
from aivee_api.db.models import Camera, RuleRow, Site
from aivee_contracts.events import AlertEvent
from aivee_contracts.rules import Condition, Rule
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_ingest.alert_message import AlertContext, basic_context


async def alert_location(sessions: async_sessionmaker[AsyncSession], event_id: str) -> str | None:
    async with sessions() as s:
        return await event_location(s, event_id)


async def telegram_chat_for(
    sessions: async_sessionmaker[AsyncSession], event_id: str
) -> str | None:
    """The location's own `telegram_chat_id`, or None (callers fall back to TELEGRAM_CHAT_ID)."""
    async with sessions() as s:
        location_id = await event_location(s, event_id)
        if location_id is None:
            return None
        site = await s.get(Site, location_id)
        return site.telegram_chat_id if site and site.telegram_chat_id else None


async def alert_context(
    sessions: async_sessionmaker[AsyncSession], event: AlertEvent
) -> AlertContext:
    """Names for the alert message: location, camera, zone, the rule's conditions and the
    stored vision check. Ids stand in for missing names; never raises on missing rows."""
    async with sessions() as s:
        view = await AlertRepository(s).view(event.event_id)
        location_id = view.location_id if view else await event_location(s, event.event_id)
        site = await s.get(Site, location_id) if location_id else None
        camera = await s.get(Camera, event.camera_id)
        row = await s.get(RuleRow, event.rule_id)
    conditions: list[Condition] = []
    if row is not None:
        try:
            conditions = Rule.model_validate(row.rule).all_of
        except ValidationError:
            conditions = []
    return AlertContext(
        event=event,
        zone_name=view.zone_name if view else basic_context(event).zone_name,
        location_name=(site.name if site and site.name else location_id or ""),
        camera_name=camera.name if camera and camera.name else event.camera_id,
        conditions=conditions,
        verification=view.verification if view else None,
    )


async def rule_conditions(
    sessions: async_sessionmaker[AsyncSession], rule_id: str
) -> list[Condition]:
    """The rule's conditions, empty when the rule is gone or unreadable."""
    async with sessions() as s:
        row = await s.get(RuleRow, rule_id)
    if row is None:
        return []
    try:
        return list(Rule.model_validate(row.rule).all_of)
    except ValidationError:
        return []
