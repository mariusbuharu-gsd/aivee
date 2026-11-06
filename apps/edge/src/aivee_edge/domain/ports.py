"""Ports: the only way domain/application code talks to the outside world.

Adapters in `aivee_edge.adapters` implement these protocols; tests use fakes.
`Image` is opaque here on purpose (a numpy array in the adapters).
"""

from typing import Protocol

from aivee_contracts.commands import EdgeCommand
from aivee_contracts.events import AlertEvent, Metrics, StaffSuggestion
from aivee_contracts.geometry import CameraConfig
from aivee_contracts.rules import Rule

from aivee_edge.domain.observation import Frame

Image = object


class FrameSource(Protocol):
    def read(self) -> tuple[float, Image] | None:
        """Next (timestamp, image), or None when the source has ended."""
        ...


class PersonDetector(Protocol):
    def detect(self, image: Image, ts: float) -> Frame:
        """Detect and track people (roles not yet assigned) and objects."""
        ...


class EventPublisher(Protocol):
    def publish_alert(self, event: AlertEvent, snapshot_jpeg: bytes | None) -> None: ...

    def publish_suggestion(
        self, suggestion: StaffSuggestion, snapshot_jpeg: bytes | None
    ) -> None: ...

    def publish_metrics(self, metrics: Metrics) -> None: ...


class CommandSource(Protocol):
    """The owner's decisions sent by the API (MQTT `commands` in production)."""

    def take_commands(self) -> list[EdgeCommand]:
        """Commands received since the last call (thread-safe; each returned once)."""
        ...


class ConfigSource(Protocol):
    """Rules and camera config pushed by the API (retained MQTT in production)."""

    def rules(self) -> list[Rule]: ...

    def camera(self) -> CameraConfig: ...
