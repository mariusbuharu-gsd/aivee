"""Ports: the only way domain/application code talks to the outside world.

Adapters in `aivee_edge.adapters` implement these protocols; tests use fakes.
`Image` is opaque here on purpose (a numpy array in the adapters).
"""

from collections.abc import Sequence
from typing import Protocol

from aivee_contracts.commands import EdgeCommand
from aivee_contracts.detections import Detections
from aivee_contracts.events import AlertEvent, Metrics, StaffSuggestion
from aivee_contracts.geometry import CameraConfig
from aivee_contracts.rules import Rule

from aivee_edge.domain.observation import Frame
from aivee_edge.domain.visual import VisualJob, VisualSample

Image = object


class FrameSource(Protocol):
    def read(self) -> tuple[float, Image] | None:
        """Next (timestamp, image), or None when the source has ended."""
        ...


class PersonDetector(Protocol):
    def detect(self, image: Image, ts: float) -> Frame:
        """Detect and track people (roles not yet assigned) and objects."""
        ...


class VisualScorer(Protocol):
    """Zero-shot image checks for `visual` conditions (CLIP in production).

    A job's score is the softmax share of its positive prompts against its negative ones,
    with the model's own temperature. The scorer may work in the background: `submit`
    hands it one frame's jobs and returns False while it is still busy with the previous
    ones; `collect` returns the scores finished since the last call, each stamped with the
    time of the frame it came from.
    """

    def prepare(self, prompts: Sequence[str]) -> None:
        """Encode and cache these text prompts (called when rules change)."""
        ...

    def submit(self, ts: float, image: Image, jobs: Sequence[VisualJob]) -> bool: ...

    def collect(self) -> list[VisualSample]: ...


class EventPublisher(Protocol):
    def publish_alert(
        self, event: AlertEvent, snapshot_jpeg: bytes | None, before_jpeg: bytes | None = None
    ) -> None:
        """`before_jpeg`: the last frame that still showed the object of an object change."""
        ...

    def publish_suggestion(
        self, suggestion: StaffSuggestion, snapshot_jpeg: bytes | None
    ) -> None: ...

    def publish_metrics(self, metrics: Metrics) -> None: ...

    def publish_detections(self, detections: Detections) -> None: ...


class CommandSource(Protocol):
    """The owner's decisions sent by the API (MQTT `commands` in production)."""

    def take_commands(self) -> list[EdgeCommand]:
        """Commands received since the last call (thread-safe; each returned once)."""
        ...


class ConfigSource(Protocol):
    """Rules and camera config pushed by the API (retained MQTT in production)."""

    def rules(self) -> list[Rule]: ...

    def camera(self) -> CameraConfig: ...
