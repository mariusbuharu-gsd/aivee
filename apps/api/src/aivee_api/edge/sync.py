"""Build the complete retained documents for one device from the DB and publish them."""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from aivee_contracts.commands import EdgeCommand
from aivee_contracts.events import StaffProfile, StaffProfiles
from aivee_contracts.geometry import DeviceConfig
from aivee_contracts.rules import RuleSet
from aivee_contracts.topics import Topics
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aivee_api.db.repositories import (
    CameraRepository,
    DeviceRepository,
    RuleRepository,
    StaffRepository,
    camera_config,
)
from aivee_api.edge.publisher import EdgePublisher, PublisherUnavailable

log = logging.getLogger(__name__)

QOS_STATE = 1


class EdgeSync:
    """Every device of the site gets its own retained documents. `device` is the API's
    default device (DEVICE env); cameras may belong to others, so a publish covers the
    default device plus every device of the site known to the DB."""

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

    async def devices(self) -> list[str]:
        async with self._sessions() as s:
            known = await DeviceRepository(s).ids_for_site(self.site)
        return [self.device, *sorted(set(known) - {self.device})]

    async def rule_set(self, device: str | None = None) -> RuleSet:
        device = device or self.device
        async with self._sessions() as s:
            rules = await RuleRepository(s).for_device(device)
        return RuleSet(device=device, rules=rules)

    async def device_config(self, device: str | None = None) -> DeviceConfig:
        device = device or self.device
        async with self._sessions() as s:
            rows = await CameraRepository(s).list_all(device_id=device)
        return DeviceConfig(device=device, cameras=[camera_config(r) for r in rows])

    async def staff_profiles(self, device: str | None = None) -> StaffProfiles:
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
        return StaffProfiles(device=device or self.device, profiles=profiles)

    def _topics(self, device: str) -> Topics:
        return Topics(site=self.site, device=device)

    async def publish_rules(self) -> bool:
        sent = [
            await self._send(self._topics(d).rules, (await self.rule_set(d)).model_dump_json())
            for d in await self.devices()
        ]
        return all(sent)

    async def publish_config(self) -> bool:
        sent = [
            await self._send(
                self._topics(d).config, (await self.device_config(d)).model_dump_json()
            )
            for d in await self.devices()
        ]
        return all(sent)

    async def publish_profiles(self) -> bool:
        sent = [
            await self._send(
                self._topics(d).profiles, (await self.staff_profiles(d)).model_dump_json()
            )
            for d in await self.devices()
        ]
        return all(sent)

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
    device_id: str = ""
    """The device that made the suggestion; empty means the API's default device."""


class EdgeCommands(Protocol):
    """Tell the edge the owner's decision on a staff suggestion."""

    async def suggestion_decided(self, decision: SuggestionDecision) -> None: ...


class LoggingEdgeCommands:
    """Records and logs decisions; used in tests and when the API runs without MQTT."""

    def __init__(self) -> None:
        self.decisions: list[SuggestionDecision] = []

    async def suggestion_decided(self, decision: SuggestionDecision) -> None:
        self.decisions.append(decision)
        log.info(
            "suggestion %s %s (MQTT disabled: not sent to the edge)",
            decision.suggestion_id,
            "confirmed" if decision.confirmed else "rejected",
        )


QOS_COMMAND = 1


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class MqttEdgeCommands:
    """Sends an `EdgeCommand` on the suggesting device's `commands` topic (QoS 1, not
    retained: a stale decision must not be replayed to a later track with the same id)."""

    def __init__(
        self,
        publisher: EdgePublisher,
        site: str,
        default_device: str,
        *,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self._publisher = publisher
        self._site = site
        self._default_device = default_device
        self._clock = clock
        self._new_id = new_id

    async def suggestion_decided(self, decision: SuggestionDecision) -> None:
        device = decision.device_id or self._default_device
        command = EdgeCommand(
            command_id=self._new_id(),
            kind="confirm_staff" if decision.confirmed else "reject_staff",
            camera_id=decision.camera_id,
            track_id=decision.track_id,
            suggestion_id=decision.suggestion_id,
            at=self._clock(),
        )
        topic = Topics(site=self._site, device=device).commands
        try:
            await self._publisher.publish(
                topic, command.model_dump_json().encode(), qos=QOS_COMMAND, retain=False
            )
        except PublisherUnavailable as e:
            # The decision is already saved; only the live track's role is not updated.
            log.warning("command %s for %s not sent (%s)", command.kind, decision.suggestion_id, e)
            return
        log.info(
            "command %s sent to %s suggestion=%s track=%d",
            command.kind,
            device,
            decision.suggestion_id,
            decision.track_id,
        )
