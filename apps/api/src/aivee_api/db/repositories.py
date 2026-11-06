"""Small repositories over an AsyncSession. Callers own the transaction (commit)."""

from collections.abc import Sequence
from datetime import UTC, datetime

from aivee_contracts.events import AlertEvent, DeviceStatus, StaffSuggestion
from aivee_contracts.geometry import CameraConfig
from aivee_contracts.rules import Rule
from pgvector.sqlalchemy import avg
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from aivee_api.db.models import (
    Camera,
    Device,
    EventRow,
    RuleRow,
    Site,
    StaffExample,
    StaffProfileRow,
    SuggestionRow,
)


class DeviceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def ensure_site(self, site_id: str) -> None:
        await self.s.execute(insert(Site).values(id=site_id, name=site_id).on_conflict_do_nothing())

    async def apply_status(self, site_id: str, status: DeviceStatus) -> None:
        await self.ensure_site(site_id)
        values = {
            "state": status.state,
            "version": status.version,
            "cameras": status.cameras,
            "last_seen": datetime.now(UTC),
        }
        stmt = insert(Device).values(id=status.device, site_id=site_id, **values)
        await self.s.execute(stmt.on_conflict_do_update(index_elements=[Device.id], set_=values))

    async def touch(self, device_id: str) -> None:
        await self.s.execute(
            update(Device).where(Device.id == device_id).values(last_seen=datetime.now(UTC))
        )

    async def get(self, device_id: str) -> Device | None:
        return await self.s.get(Device, device_id)


class CameraRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def upsert(self, camera: CameraConfig, device_id: str | None = None) -> None:
        values = {
            "name": camera.name,
            "source": camera.source,
            "zones": [z.model_dump(mode="json") for z in camera.zones],
            "device_id": device_id,
        }
        stmt = insert(Camera).values(id=camera.id, **values)
        await self.s.execute(stmt.on_conflict_do_update(index_elements=[Camera.id], set_=values))

    async def get(self, camera_id: str) -> Camera | None:
        return await self.s.get(Camera, camera_id)


class RuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def upsert(self, rule: Rule) -> None:
        values = {
            "camera_id": rule.camera_id,
            "rule": rule.model_dump(mode="json"),
            "prompt_ro": rule.prompt_ro,
            "enabled": rule.enabled,
        }
        stmt = insert(RuleRow).values(id=rule.id, **values)
        await self.s.execute(stmt.on_conflict_do_update(index_elements=[RuleRow.id], set_=values))

    async def for_camera(self, camera_id: str) -> list[Rule]:
        rows = await self.s.scalars(select(RuleRow).where(RuleRow.camera_id == camera_id))
        return [Rule.model_validate(r.rule) for r in rows]


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def insert_if_new(
        self, event: AlertEvent, device_id: str = "", snapshot_path: str | None = None
    ) -> bool:
        """Store the event once per event_id. True only when this call inserted it."""
        stmt = (
            insert(EventRow)
            .values(
                event_id=event.event_id,
                device_id=device_id,
                rule_id=event.rule_id,
                camera_id=event.camera_id,
                zone_id=event.zone_id,
                state=event.state,
                at=event.at,
                summary_ro=event.summary_ro,
                snapshot_path=snapshot_path,
            )
            .on_conflict_do_nothing(index_elements=[EventRow.event_id])
            .returning(EventRow.id)
        )
        return (await self.s.execute(stmt)).first() is not None

    async def get(self, event_id: str) -> EventRow | None:
        return await self.s.scalar(select(EventRow).where(EventRow.event_id == event_id))

    async def recent(self, limit: int = 50) -> Sequence[EventRow]:
        rows = await self.s.scalars(select(EventRow).order_by(EventRow.at.desc()).limit(limit))
        return rows.all()


class SuggestionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def insert_if_new(self, suggestion: StaffSuggestion, device_id: str = "") -> bool:
        stmt = (
            insert(SuggestionRow)
            .values(device_id=device_id, **suggestion.model_dump())
            .on_conflict_do_nothing(index_elements=[SuggestionRow.suggestion_id])
            .returning(SuggestionRow.id)
        )
        return (await self.s.execute(stmt)).first() is not None

    async def set_status(self, suggestion_id: str, status: str) -> None:
        await self.s.execute(
            update(SuggestionRow)
            .where(SuggestionRow.suggestion_id == suggestion_id)
            .values(status=status)
        )

    async def pending(self) -> Sequence[SuggestionRow]:
        rows = await self.s.scalars(select(SuggestionRow).where(SuggestionRow.status == "pending"))
        return rows.all()


class StaffRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def create_profile(
        self, profile_id: str, name: str, description_ro: str = ""
    ) -> StaffProfileRow:
        row = StaffProfileRow(id=profile_id, name=name, description_ro=description_ro)
        self.s.add(row)
        await self.s.flush()
        return row

    async def add_example(
        self, profile_id: str, embedding: Sequence[float], source: str = "upload"
    ) -> None:
        self.s.add(StaffExample(profile_id=profile_id, embedding=list(embedding), source=source))
        await self.s.flush()

    async def set_centroid(self, profile_id: str, centroid: Sequence[float]) -> None:
        await self.s.execute(
            update(StaffProfileRow)
            .where(StaffProfileRow.id == profile_id)
            .values(centroid=list(centroid))
        )

    async def recompute_centroid(self, profile_id: str) -> None:
        """Centroid = mean of the profile's examples (callers L2-normalise if needed)."""
        mean = await self.s.scalar(
            select(avg(StaffExample.embedding)).where(StaffExample.profile_id == profile_id)
        )
        if mean is not None:
            await self.set_centroid(profile_id, [float(x) for x in mean])

    async def nearest_profile(
        self, embedding: Sequence[float]
    ) -> tuple[StaffProfileRow, float] | None:
        """Closest profile by cosine distance, or None when no profile has a centroid."""
        distance = StaffProfileRow.centroid.cosine_distance(list(embedding)).label("d")
        row = (
            await self.s.execute(
                select(StaffProfileRow, distance)
                .where(StaffProfileRow.centroid.is_not(None))
                .order_by(distance)
                .limit(1)
            )
        ).first()
        return (row[0], float(row[1])) if row else None
