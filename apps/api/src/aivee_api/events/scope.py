"""What one /ws/events connection may receive: alerts (raw rows and folded AlertViews) and
detections of the user's locations (alerts.view) and staff suggestions where they may review
them (staff.review)."""

from collections.abc import Collection

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_api.alerts.schemas import AlertViewMessage
from aivee_api.db.models import Camera, Device
from aivee_api.events.schemas import AlertMessage, DetectionsMessage, SuggestionMessage


class LiveScope:
    def __init__(self, alert_locations: Collection[str], suggestion_locations: Collection[str]):
        self._alerts = set(alert_locations)
        self._suggestions = set(suggestion_locations)
        self._device_site: dict[str, str] = {}
        self._camera_site: dict[str, str] = {}

    @property
    def alert_locations(self) -> frozenset[str]:
        return frozenset(self._alerts)

    async def refresh(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        """Reload device → location and camera → location (cheap: a handful of rows)."""
        async with sessions() as s:
            devices = (await s.execute(select(Device.id, Device.site_id))).all()
            cameras = (await s.execute(select(Camera.id, Camera.device_id))).all()
        self._device_site = {d: site for d, site in devices}
        self._camera_site = {c: self._device_site[d] for c, d in cameras if d in self._device_site}

    def _location(self, device_id: str, camera_id: str) -> str | None:
        return self._device_site.get(device_id) or self._camera_site.get(camera_id)

    def allows(self, message: BaseModel) -> bool:
        if isinstance(message, AlertViewMessage):
            return message.data.location_id in self._alerts
        if isinstance(message, AlertMessage):
            loc = self._location(message.data.device_id, message.data.camera_id)
            return loc in self._alerts
        if isinstance(message, SuggestionMessage):
            loc = self._location(message.data.device_id, message.data.camera_id)
            return loc in self._suggestions
        if isinstance(message, DetectionsMessage):
            return self._camera_site.get(message.camera_id) in self._alerts
        return False
