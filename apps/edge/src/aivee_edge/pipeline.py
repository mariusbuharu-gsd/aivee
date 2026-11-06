"""The edge application loop: one `step` per frame, every stage behind a port.

source.read → detector.detect → (pose → raised hand at tables; stance from pose or box
shape) → trajectory + stance ratio →
behaviour features → (appearance vs staff profiles) → roles → situation engine →
publish alerts (with snapshot on open), staff suggestions (with a person crop), live
detections (<= 5 Hz) and periodic metrics. Owner commands (confirm/reject staff) are
applied at the start of every step.

Rules and zones are re-read from the `ConfigSource` on every frame and applied when
they change, so edits in the dashboard take effect without a restart.
"""

import logging
import threading
import uuid
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Protocol

from aivee_contracts.detections import DetectedObject, DetectedTrack, Detections
from aivee_contracts.events import AlertEvent, Metrics, StaffProfiles, StaffSuggestion
from aivee_contracts.geometry import Zone
from aivee_contracts.rules import Rule

from aivee_edge.domain.appearance import HIGH_SIMILARITY, LOW_SIMILARITY, appearance_score
from aivee_edge.domain.behaviour import BehaviourFeatures, TrajectoryBuffer
from aivee_edge.domain.engine import SituationEngine, utc_from_timestamp
from aivee_edge.domain.geometry import foot_point, point_in_polygon
from aivee_edge.domain.observation import BBox, Frame, TrackObs
from aivee_edge.domain.ports import (
    CommandSource,
    ConfigSource,
    EventPublisher,
    FrameSource,
    Image,
    PersonDetector,
)
from aivee_edge.domain.pose import Keypoint, is_raised_hand
from aivee_edge.domain.role import RoleClassifier
from aivee_edge.domain.stance import is_standing
from aivee_edge.metrics import MetricsMeter, cpu_percent

log = logging.getLogger("aivee_edge.pipeline")

TABLE_TAG = "table"
STAFF_TAG = "staff"


class PoseEstimator(Protocol):
    def estimate(
        self, image: Image, tracks: Sequence[TrackObs]
    ) -> Mapping[int, Sequence[Keypoint]]:
        """COCO-17 keypoints (normalised x, y, confidence) per track id of `tracks`."""
        ...


class Embedder(Protocol):
    def embed(self, image: Image, bbox: BBox) -> Sequence[float] | None:
        """L2-normalised appearance embedding of the person crop, or None if unusable."""
        ...


class SnapshotMaker(Protocol):
    def make(self, image: Image) -> bytes | None:
        """Face-blurred JPEG of the frame, or None."""
        ...

    def crop(self, image: Image, bbox: BBox) -> bytes | None:
        """Face-blurred JPEG of one person (normalised bbox, slightly padded), or None."""
        ...


class NoSnapshot:
    def make(self, image: Image) -> bytes | None:
        return None

    def crop(self, image: Image, bbox: BBox) -> bytes | None:
        return None


@dataclass
class StepResult:
    frame: Frame
    events: list[AlertEvent] = field(default_factory=list)
    suggestions: list[StaffSuggestion] = field(default_factory=list)
    metrics: Metrics | None = None
    verified: bool = False


def _new_id() -> str:
    return str(uuid.uuid4())


def _clamp(bbox: BBox) -> BBox:
    """Detector boxes can overshoot the frame by a hair; the contract wants [0, 1]."""
    x1, y1, x2, y2 = (min(1.0, max(0.0, c)) for c in bbox)
    return (x1, y1, x2, y2)


class EdgePipeline:
    def __init__(
        self,
        source: FrameSource,
        detector: PersonDetector,
        publisher: EventPublisher,
        config: ConfigSource,
        *,
        device: str,
        camera_id: str,
        pose: PoseEstimator | None = None,
        embedder: Embedder | None = None,
        profiles: Callable[[], StaffProfiles | None] | None = None,
        snapshots: SnapshotMaker | None = None,
        commands: CommandSource | None = None,
        grace_s: float = 1.5,
        arrive_s: float | None = 5.0,
        embed_interval_s: float = 2.0,
        appearance_low: float = LOW_SIMILARITY,
        appearance_high: float = HIGH_SIMILARITY,
        forget_after_s: float = 5.0,
        metrics_interval_s: float = 5.0,
        detections_interval_s: float = 0.2,
        id_factory: Callable[[], str] = _new_id,
        to_datetime: Callable[[float], datetime] = utc_from_timestamp,
        cpu: Callable[[], float] = cpu_percent,
    ) -> None:
        self._source = source
        self._detector = detector
        self._publisher = publisher
        self._config = config
        self._pose = pose
        self._embedder = embedder
        self._profiles = profiles
        self._snapshots = snapshots or NoSnapshot()
        self._commands = commands
        self._camera_id = camera_id
        self._seen_commands: deque[str] = deque(maxlen=1000)
        self._to_datetime = to_datetime
        self._detections_interval_s = detections_interval_s
        self._detections_at = -float("inf")
        self._embed_interval_s = embed_interval_s
        self._appearance_low = appearance_low
        self._appearance_high = appearance_high
        self._forget_after_s = forget_after_s

        self._rules: list[Rule] = []
        self._zones: list[Zone] = []
        self._tables: dict[str, list[tuple[float, float]]] = {}
        self._staff_zones: dict[str, list[tuple[float, float]]] = {}
        self.engine = SituationEngine(
            [],
            [],
            id_factory,
            camera_id,
            to_datetime=to_datetime,
            grace_s=grace_s,
            arrive_s=arrive_s,
        )
        self.buffer = TrajectoryBuffer()
        self.classifier = RoleClassifier(camera_id, id_factory)
        self.meter = MetricsMeter(device, metrics_interval_s, cpu)
        self._last_seen: dict[int, float] = {}
        self._appearance: dict[int, float | None] = {}
        self._embedded_at: dict[int, float] = {}

    # -- config --------------------------------------------------------------------

    @property
    def zones(self) -> list[Zone]:
        return list(self._zones)

    @property
    def rules(self) -> list[Rule]:
        return list(self._rules)

    def reload(self) -> None:
        """Apply rules/zones from the ConfigSource if they changed."""
        rules = self._config.rules()
        if rules != self._rules:
            self._rules = rules
            self.engine.update_rules(rules)
            log.info("rules reloaded count=%d ids=%s", len(rules), ",".join(r.id for r in rules))
        try:
            zones = list(self._config.camera().zones)
        except LookupError:
            zones = []
        if zones != self._zones:
            self._zones = zones
            self.engine.update_zones(zones)
            self._tables = {z.id: list(z.polygon) for z in zones if z.tag == TABLE_TAG}
            self._staff_zones = {z.id: list(z.polygon) for z in zones if z.tag == STAFF_TAG}
            log.info(
                "zones reloaded count=%d names=%s", len(zones), ",".join(z.name for z in zones)
            )

    def apply_commands(self) -> None:
        """Apply the owner's confirm/reject decisions to the tracks they name.

        Runs on the pipeline thread, so the classifier is never touched concurrently.
        Commands for another camera, a track that is no longer tracked or an id already
        applied (QoS 1 may redeliver) are dropped.
        """
        if self._commands is None:
            return
        for cmd in self._commands.take_commands():
            if cmd.command_id in self._seen_commands:
                continue
            self._seen_commands.append(cmd.command_id)
            if cmd.camera_id != self._camera_id or cmd.track_id not in self._last_seen:
                log.info(
                    "command_ignored command_id=%s kind=%s camera=%s track=%d",
                    cmd.command_id,
                    cmd.kind,
                    cmd.camera_id,
                    cmd.track_id,
                )
                continue
            if cmd.kind == "confirm_staff":
                self.classifier.confirm(cmd.track_id)
            else:
                self.classifier.reject(cmd.track_id)
            log.info(
                "command_applied command_id=%s kind=%s track=%d suggestion_id=%s",
                cmd.command_id,
                cmd.kind,
                cmd.track_id,
                cmd.suggestion_id,
            )

    # -- loop ----------------------------------------------------------------------

    def step(self) -> StepResult | None:
        """Process one frame; None when the source has ended."""
        item = self._source.read()
        if item is None:
            return None
        ts, image = item
        self.reload()
        self.apply_commands()

        frame = self._detector.detect(image, ts)
        centroids = self._centroids()
        frame, posed = self._poses(image, frame, everyone=bool(centroids))
        appearance, embedded = self._appearance_scores(image, frame, centroids)

        self.buffer.observe(frame)
        features: dict[int, BehaviourFeatures] = {
            t.track_id: self.buffer.features(t.track_id, self._tables, self._staff_zones)
            for t in frame.tracks
        }
        frame, suggestions = self.classifier.assign(frame, features, appearance)
        events = self.engine.step(frame)

        for event in events:
            snapshot = self._snapshots.make(image) if event.state == "opened" else None
            self._publisher.publish_alert(event, snapshot)
            log.info(
                "alert event_id=%s state=%s rule=%s camera=%s zone=%s snapshot=%s summary=%r",
                event.event_id,
                event.state,
                event.rule_id,
                event.camera_id,
                event.zone_id,
                snapshot is not None,
                event.summary_ro,
            )
        boxes = {t.track_id: t.bbox for t in frame.tracks}
        for suggestion in suggestions:
            # The crop lets the API learn this person's appearance if the owner confirms.
            crop = self._snapshots.crop(image, boxes[suggestion.track_id])
            self._publisher.publish_suggestion(suggestion, crop)
            log.info(
                "staff_suggestion suggestion_id=%s track=%d score=%.2f snapshot=%s reason=%r",
                suggestion.suggestion_id,
                suggestion.track_id,
                suggestion.staff_score,
                crop is not None,
                suggestion.reason_ro,
            )

        self._publish_detections(frame)
        self._forget_gone(frame, ts)
        verified = posed or embedded
        metrics = self.meter.record(ts, verified)
        if metrics is not None:
            self._publisher.publish_metrics(metrics)
            log.info(
                "metrics fps=%.1f verified_ratio=%.2f cpu=%.0f tracks=%d",
                metrics.fps,
                metrics.verified_ratio,
                metrics.cpu_percent,
                len(frame.tracks),
            )
        return StepResult(frame, events, suggestions, metrics, verified)

    def run(self, stop: threading.Event | None = None) -> int:
        """Step until the source ends or `stop` is set; returns the number of frames."""
        frames = 0
        while stop is None or not stop.is_set():
            if self.step() is None:
                break
            frames += 1
        return frames

    # -- stages --------------------------------------------------------------------

    def _in_table(self, track: TrackObs) -> bool:
        p = foot_point(track.bbox)
        return any(point_in_polygon(p, poly) for poly in self._tables.values())

    def _poses(self, image: Image, frame: Frame, *, everyone: bool) -> tuple[Frame, bool]:
        """Raised hands (table zones only) and per-frame stance.

        Pose runs for people at a table (raised hand), and for everyone while appearance
        scoring is active, because the standing signal only counts next to appearance.
        Without keypoints the stance falls back to the box shape.
        """
        seated = [t for t in frame.tracks if self._in_table(t)]
        at_table = {t.track_id for t in seated}
        targets = list(frame.tracks) if everyone else seated
        keypoints: Mapping[int, Sequence[Keypoint]] = {}
        posed = False
        if self._pose is not None and targets:
            keypoints = self._pose.estimate(image, targets)
            posed = True
        tracks = tuple(
            replace(
                t,
                raised_hand=t.track_id in at_table
                and t.track_id in keypoints
                and is_raised_hand(keypoints[t.track_id]),
                standing=is_standing(keypoints.get(t.track_id), t.bbox, frame.aspect),
            )
            for t in frame.tracks
        )
        return replace(frame, tracks=tracks), posed

    def _centroids(self) -> list[list[float]]:
        """Staff profile centroids when appearance scoring is possible, else []."""
        if self._embedder is None or self._profiles is None:
            return []
        profiles = self._profiles()
        return [list(p.centroid) for p in profiles.profiles] if profiles else []

    def _appearance_scores(
        self, image: Image, frame: Frame, centroids: Sequence[Sequence[float]]
    ) -> tuple[dict[int, float | None], bool]:
        """Appearance score per track, re-embedding each track at most every interval."""
        if self._embedder is None or not centroids:
            return {}, False
        embedded = False
        for t in frame.tracks:
            last = self._embedded_at.get(t.track_id)
            if last is not None and frame.ts - last < self._embed_interval_s:
                continue
            vector = self._embedder.embed(image, t.bbox)
            embedded = True
            self._embedded_at[t.track_id] = frame.ts
            if vector is not None:
                self._appearance[t.track_id] = appearance_score(
                    vector, centroids, low=self._appearance_low, high=self._appearance_high
                )
        return {t.track_id: self._appearance.get(t.track_id) for t in frame.tracks}, embedded

    def _publish_detections(self, frame: Frame) -> None:
        """Live overlay for the dashboard, throttled to `detections_interval_s`."""
        if frame.ts - self._detections_at + 1e-6 < self._detections_interval_s:
            return
        self._detections_at = frame.ts
        detections = Detections(
            camera_id=self._camera_id,
            ts=self._to_datetime(frame.ts),
            tracks=[
                DetectedTrack(
                    track_id=t.track_id,
                    bbox=_clamp(t.bbox),
                    role=t.role,
                    staff_score=min(1.0, max(0.0, t.staff_score)),
                    raised_hand=t.raised_hand,
                )
                for t in frame.tracks
            ],
            objects=[DetectedObject(label=o.label, bbox=_clamp(o.bbox)) for o in frame.objects],
        )
        self._publisher.publish_detections(detections)

    def _forget_gone(self, frame: Frame, ts: float) -> None:
        for t in frame.tracks:
            if t.track_id not in self._last_seen:
                log.info("track_new track=%d role=%s", t.track_id, t.role)
            self._last_seen[t.track_id] = ts
        gone = [tid for tid, seen in self._last_seen.items() if ts - seen > self._forget_after_s]
        for tid in gone:
            del self._last_seen[tid]
            self.buffer.forget(tid)
            self.classifier.forget(tid)
            self._appearance.pop(tid, None)
            self._embedded_at.pop(tid, None)
            log.info("track_gone track=%d", tid)

    def appearance_of(self, track_id: int) -> float | None:
        """Last appearance score of a track (None: not embedded or no profiles)."""
        return self._appearance.get(track_id)

    def tracked_ids(self) -> set[int]:
        return set(self._last_seen)
