"""Build the complete retained documents for one device from the DB and publish them."""

import logging
from dataclasses import dataclass
from typing import Protocol

from aivee_contracts.events import StaffProfile, StaffProfiles
from aivee_contracts.geometry import DeviceConfig
from aivee_contracts.rules import RuleSet
from aivee_contracts.topics import Topics
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_api.db.repositories import (
    CameraRepository,
    RuleRepository,
    StaffRepository,
    camera_config,
)
from aivee_api.edge.publisher import EdgePublisher, PublisherUnavailable

log = logging.getLogger(__name__)

QOS_STATE = 1


class EdgeSync:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        publisher: EdgePublisher,
        site: str,
        device: str,
    ) -> None:
        self._sessions = sessions
        self._publisher = publisher
        self.site = site
        self.device = device
        self.topics = Topics(site=site, device=device)

    async def rule_set(self) -> RuleSet:
        async with self._sessions() as s:
            rules = await RuleRepository(s).for_device(self.device)
        return RuleSet(device=self.device, rules=rules)

    async def device_config(self) -> DeviceConfig:
        async with self._sessions() as s:
            rows = await CameraRepository(s).list_all(device_id=self.device)
        return DeviceConfig(device=self.device, cameras=[camera_config(r) for r in rows])

    async def staff_profiles(self) -> StaffProfiles:
        async with self._sessions() as s:
            rows = await StaffRepository(s).profiles()
        profiles = [
            StaffProfile(
                id=r.id,
                name=r.name,
                description_ro=r.description_ro,
                centroid=[float(x) for x in r.centroid],
            )
            for r in rows
            if r.centroid is not None
        ]
        return StaffProfiles(device=self.device, profiles=profiles)

    async def publish_rules(self) -> bool:
        return await self._send(self.topics.rules, (await self.rule_set()).model_dump_json())

    async def publish_config(self) -> bool:
        return await self._send(self.topics.config, (await self.device_config()).model_dump_json())

    async def publish_profiles(self) -> bool:
        payload = (await self.staff_profiles()).model_dump_json()
        return await self._send(self.topics.profiles, payload)

    async def publish_all(self) -> None:
        await self.publish_config()
        await self.publish_rules()
        await self.publish_profiles()

    async def _send(self, topic: str, payload: str) -> bool:
        """Publish retained; a missing broker is logged, not raised (re-sent on reconnect)."""
        try:
            await self._publisher.publish(topic, payload.encode(), qos=QOS_STATE, retain=True)
        except PublisherUnavailable as e:
            log.warning("could not publish %s (%s); it will be re-sent on reconnect", topic, e)
            return False
        return True


@dataclass(frozen=True)
class SuggestionDecision:
    suggestion_id: str
    camera_id: str
    track_id: int
    confirmed: bool


class EdgeCommands(Protocol):
    """Tell the edge the owner's decision on a staff suggestion.

    There is no contract/ACL topic for this yet (the edge may only read rules, profiles and
    config), so the default implementation only logs. When a `commands` topic exists, an
    MQTT implementation plugs in here without touching the staff service.
    """

    async def suggestion_decided(self, decision: SuggestionDecision) -> None: ...


class LoggingEdgeCommands:
    def __init__(self) -> None:
        self.decisions: list[SuggestionDecision] = []

    async def suggestion_decided(self, decision: SuggestionDecision) -> None:
        self.decisions.append(decision)
        log.info(
            "suggestion %s %s (not sent to the edge: no commands topic yet)",
            decision.suggestion_id,
            "confirmed" if decision.confirmed else "rejected",
        )
