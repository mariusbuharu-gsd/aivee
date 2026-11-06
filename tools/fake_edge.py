"""Fake edge device: scripted people through the REAL edge pipeline, published over MQTT.

No camera or models: a scenario yields synthetic Frames which go through EdgePipeline
(behaviour, roles, situation engine), so alerts are produced by the same code as on a
real device. Publishes as the edge MQTT user from .env.

    uv run python tools/fake_edge.py --scenario unattended --speed 10
    make fake-edge SCENARIO=hand

Scenarios (simulated seconds; --speed compresses wall time):
  unattended  two guests sit at Masa 1; nobody comes; alert opens at 60 s; a waiter who
              walks between the other tables and the kitchen comes to Masa 1 at 90 s
              and stays → arrived at 95 s (ARRIVE_S = 5 s) → closes
  hand        a guest at Masa 2 raises a hand → opens; hand down → closes
  queue       three guests wait at the entrance with no staff → opens; seated → closes
  uncleared   guests leave Masa 3 with cups on it → opens after 60 s; cleared → closes

Zones come from the retained `config` (DeviceConfig): the camera is --camera-id, else the
first retained camera with zones, and the scenario's places (Masa 1, Intrare, ...) map onto
its zones by tag, so alerts carry the dashboard's camera and zone ids. The waiter always
serves the zone the guests sit in, even when retained zones overlap; extra `demo-*` zones
only give him tables to walk between. Rules come from the
retained `rules` for that camera. When nothing is retained (or with --demo) a built-in demo
layout and rule set is used, and the script says so.
"""

import argparse
import logging
import sys
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from aivee_contracts.detections import Detections
from aivee_contracts.events import AlertEvent, Metrics, StaffSuggestion
from aivee_contracts.geometry import CameraConfig, DeviceConfig, Zone
from aivee_contracts.rules import Action, Condition, Rule
from aivee_edge.domain.geometry import point_in_polygon
from aivee_edge.domain.observation import BBox, Frame, ObjectObs, TrackObs
from aivee_edge.domain.ports import ConfigSource, EventPublisher, Image
from aivee_edge.domain.pose import Keypoint
from aivee_edge.pipeline import EdgePipeline

log = logging.getLogger("fake_edge")

# -- demo layout -----------------------------------------------------------------------


def _square(x: float, y: float, size: float = 0.25) -> list[tuple[float, float]]:
    return [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]


DEMO_ZONES = [
    Zone(id="masa-1", name="Masa 1", tag="table", polygon=_square(0.05, 0.05)),
    Zone(id="masa-2", name="Masa 2", tag="table", polygon=_square(0.70, 0.05)),
    Zone(id="masa-3", name="Masa 3", tag="table", polygon=_square(0.05, 0.55)),
    Zone(id="masa-4", name="Masa 4", tag="table", polygon=_square(0.70, 0.55)),
    Zone(id="bucatarie", name="Bucătărie", tag="staff", polygon=_square(0.40, 0.72)),
    Zone(id="intrare", name="Intrare", tag="entrance", polygon=_square(0.40, 0.05, 0.2)),
]
ZONE = {z.id: z for z in DEMO_ZONES}


def demo_camera(camera_id: str) -> CameraConfig:
    return CameraConfig(id=camera_id, name="Sala (demo)", source="fake", zones=DEMO_ZONES)


def demo_rules(camera_id: str) -> list[Rule]:
    def rule(rule_id: str, name: str, prompt: str, tag: str, *conds: Condition) -> Rule:
        return Rule(
            id=rule_id,
            camera_id=camera_id,
            name=name,
            prompt_ro=prompt,
            zone_tag=tag,
            all_of=list(conds),
            action=Action(type="telegram"),
            cooldown_s=300,
        )

    return [
        rule(
            "demo-unattended",
            "Masă neservită",
            "Anunță-mă dacă la o masă stau clienți de un minut și nu a venit nimeni.",
            "table",
            Condition(kind="present", role="guest", min_duration_s=60),
            Condition(kind="absent", role="staff", min_duration_s=60),
        ),
        rule(
            "demo-hand",
            "Clientul cheamă",
            "Anunță-mă când un client ridică mâna.",
            "table",
            Condition(kind="pose", role="guest", pose="raised_hand"),
        ),
        rule(
            "demo-queue",
            "Coadă la intrare",
            "Anunță-mă dacă așteaptă trei oameni la intrare și nu îi întâmpină nimeni.",
            "entrance",
            Condition(kind="count", role="guest", min_count=3),
            Condition(kind="absent", role="staff", min_duration_s=10),
        ),
        rule(
            "demo-uncleared",
            "Masă nedebarasată",
            "Anunță-mă dacă rămân pahare pe o masă liberă mai mult de un minut.",
            "table",
            Condition(
                kind="objects_unattended", objects=["cup", "bowl", "bottle"], min_duration_s=60
            ),
        ),
    ]


# -- layout: where the scenario's places are ------------------------------------------------


def _width(zone: Zone) -> float:
    xs = [p[0] for p in zone.polygon]
    return max(xs) - min(xs)


DEMO_WIDTH = _width(DEMO_ZONES[0])


def _box(zone: Zone) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in zone.polygon], [p[1] for p in zone.polygon]
    return min(xs), min(ys), max(xs), max(ys)


def _overlaps(a: Zone, b: Zone, margin: float = 0.0) -> bool:
    ax1, ay1, ax2, ay2 = _box(a)
    bx1, by1, bx2, by2 = _box(b)
    return ax1 - margin < bx2 and bx1 < ax2 + margin and ay1 - margin < by2 and by1 < ay2 + margin


SPREAD = 0.05
"""How far (demo-sized) scripted people stand from a place's spot: guests side by side."""


def _spot(zone: Zone, others: Sequence[Zone], spread: float) -> tuple[float, float]:
    """Where people stand in `zone`: its centre, unless that (or a neighbour `spread`
    away) is also inside another zone; then the free point closest to the centre."""
    centre = _centre(zone)
    x1, y1, x2, y2 = _box(zone)
    steps = 40
    candidates = [
        (x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * j / steps)
        for i in range(1, steps)
        for j in range(1, steps)
    ]

    def free(p: tuple[float, float]) -> bool:
        row = [(p[0] + d, p[1]) for d in (-spread, 0.0, spread)]
        return all(point_in_polygon(q, zone.polygon) for q in row) and not any(
            point_in_polygon(q, o.polygon) for q in row for o in others
        )

    if free(centre):
        return centre
    spots = [p for p in candidates if free(p)]
    if not spots:
        return centre
    return min(spots, key=lambda p: (p[0] - centre[0]) ** 2 + (p[1] - centre[1]) ** 2)


def _centre(zone: Zone) -> tuple[float, float]:
    poly = zone.polygon
    return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))


@dataclass(frozen=True)
class Layout:
    """The camera the pipeline sees, which zone each scenario place is, and where the
    waiter walks.

    Scenarios are scripted against the demo places (`masa-1`, `intrare`, ...). On a retained
    camera a place is the retained zone with the same tag and index; a place without one
    (more demo tables than retained ones) is the first retained zone of its tag, so a
    scenario's guests, and the waiter who serves them, are always in the same zone.

    `waypoints` only drive behaviour: the waiter needs several tables and the kitchen to
    walk through to be recognised as staff. A waypoint is a retained zone only when it
    overlaps no other zone (else walking there would also count at the guests' table);
    otherwise it is a `demo-*` zone added where it overlaps no retained zone. People
    stand at `spots`: inside their zone and, when zones overlap, outside the others."""

    camera: CameraConfig
    places: dict[str, Zone]
    waypoints: dict[str, Zone]
    missing_tags: list[str] = field(default_factory=list)
    spots: dict[str, tuple[float, float]] = field(default_factory=dict)

    @classmethod
    def demo(cls, camera_id: str) -> "Layout":
        return cls(demo_camera(camera_id), dict(ZONE), dict(ZONE))

    @classmethod
    def from_camera(cls, camera: CameraConfig) -> "Layout":
        by_tag: dict[str, list[Zone]] = {}
        for zone in camera.zones:
            by_tag.setdefault(zone.tag, []).append(zone)
        seen: dict[str, int] = {}
        places: dict[str, Zone] = {}
        waypoints: dict[str, Zone] = {}
        extras: list[Zone] = []
        missing: list[str] = []
        for demo in DEMO_ZONES:
            i = seen.get(demo.tag, 0)
            seen[demo.tag] = i + 1
            zones = by_tag.get(demo.tag, [])
            if not zones and demo.tag not in missing:
                missing.append(demo.tag)
            own = zones[i] if i < len(zones) else None
            clean = own is not None and not any(
                _overlaps(own, z) for z in camera.zones if z is not own
            )
            stand_in = demo
            needs_stand_in = own is None or (not clean and demo.id in WAITER_ROUND)
            if needs_stand_in and not any(_overlaps(demo, z) for z in camera.zones):
                stand_in = demo.model_copy(
                    update={"id": f"demo-{demo.id}", "name": f"{demo.name} (demo)"}
                )
                extras.append(stand_in)
            places[demo.id] = own or (zones[0] if zones else stand_in)
            waypoints[demo.id] = own if clean and own is not None else stand_in
        pipeline_camera = camera.model_copy(update={"zones": [*camera.zones, *extras]})
        spots: dict[str, tuple[float, float]] = {}
        for place, zone in places.items():
            others = [z for z in pipeline_camera.zones if z.id != zone.id]
            scale = min(1.0, _width(zone) / DEMO_WIDTH)
            spots[place] = _spot(zone, others, SPREAD * scale)
        return cls(pipeline_camera, places, waypoints, missing, spots)

    @staticmethod
    def _centre_of(zone: Zone) -> tuple[float, float]:
        return _centre(zone)

    def centre(self, place: str) -> tuple[float, float]:
        """Where people stand at `place` (its spot; the zone's centre on the demo layout)."""
        return self.spots.get(place) or _centre(self.places[place])

    def waypoint(self, place: str) -> tuple[float, float]:
        return _centre(self.waypoints[place])

    def scale(self, place: str) -> float:
        """Offsets inside a place are scripted for demo-sized zones; shrink them to fit."""
        return min(1.0, _width(self.places[place]) / DEMO_WIDTH)


def pick_camera(config: DeviceConfig | None, camera_id: str | None) -> CameraConfig | None:
    """The retained camera to run on: the requested id, else the first one with zones."""
    if config is None:
        return None
    if camera_id is not None:
        return next((c for c in config.cameras if c.id == camera_id and c.zones), None)
    return next((c for c in config.cameras if c.zones), None)


# -- scenarios ---------------------------------------------------------------------------


def _clamp(v: float) -> float:
    return min(1.0, max(0.0, v))


def _person(track_id: int, x: float, y: float, hand: bool = False) -> TrackObs:
    """A person whose feet are at (x, y); `hand` asks the scripted pose for a raised hand."""
    box: BBox = (_clamp(x - 0.03), _clamp(y - 0.15), _clamp(x + 0.03), _clamp(y))
    return TrackObs(track_id=track_id, bbox=box, raised_hand=hand)


def _at(layout: Layout, track_id: int, place: str, dx: float = 0.0, hand: bool = False) -> TrackObs:
    x, y = layout.centre(place)
    return _person(track_id, x + dx * layout.scale(place), y, hand)


def _object(layout: Layout, label: str, place: str, dx: float = 0.0) -> ObjectObs:
    x, y = layout.centre(place)
    x += dx * layout.scale(place)
    box: BBox = (_clamp(x - 0.02), _clamp(y - 0.04), _clamp(x + 0.02), _clamp(y))
    return ObjectObs(label=label, bbox=box)


WAITER_ROUND = ["masa-2", "masa-4", "bucatarie", "masa-3", "bucatarie", "masa-4"]


def _walking(
    points: Sequence[tuple[float, float]], t: float, leg_s: float = 4.0
) -> tuple[float, float]:
    leg = int(t // leg_s) % len(points)
    a, b = points[leg], points[(leg + 1) % len(points)]
    f = (t % leg_s) / leg_s
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def waiter_round(layout: Layout, avoid: str) -> list[tuple[float, float]]:
    """Waypoints of a waiter who keeps busy everywhere except at the `avoid` place."""
    target = layout.places[avoid]
    stops = [layout.waypoints[s] for s in WAITER_ROUND]
    points = [Layout._centre_of(z) for z in stops if not _overlaps(z, target, margin=0.02)]
    return points or [layout.waypoint("bucatarie")]


Script = Callable[[float, Layout], tuple[list[TrackObs], list[ObjectObs]]]


@dataclass(frozen=True)
class Scenario:
    name: str
    duration_s: float
    script: Script
    expects: tuple[str, ...] = field(default=())
    """Rule ids whose alert should open (and close) with the demo rules."""


def _unattended(t: float, layout: Layout) -> tuple[list[TrackObs], list[ObjectObs]]:
    tracks = [_at(layout, 1, "masa-1", -0.04), _at(layout, 2, "masa-1", 0.04)]
    if 5 <= t < 90:
        tracks.append(_person(7, *_walking(waiter_round(layout, "masa-1"), t - 5)))
    elif t >= 90:
        tracks.append(_at(layout, 7, "masa-1"))  # the waiter comes and stays (ARRIVE_S)
    return tracks, []


def _hand(t: float, layout: Layout) -> tuple[list[TrackObs], list[ObjectObs]]:
    raised = 5 <= t < 10
    return [_at(layout, 3, "masa-2", hand=raised), _at(layout, 4, "masa-2", 0.05)], []


def _queue(t: float, layout: Layout) -> tuple[list[TrackObs], list[ObjectObs]]:
    if t < 30:
        arrived = min(3, 1 + int(t // 3))
        return [_at(layout, 10 + i, "intrare", dx=(i - 1) * 0.05) for i in range(arrived)], []
    return [_at(layout, 10 + i, "masa-4", dx=(i - 1) * 0.05) for i in range(3)], []  # seated


def _uncleared(t: float, layout: Layout) -> tuple[list[TrackObs], list[ObjectObs]]:
    things = [_object(layout, "cup", "masa-3", -0.03), _object(layout, "bowl", "masa-3", 0.03)]
    if t < 15:
        return [_at(layout, 20, "masa-3", -0.04), _at(layout, 21, "masa-3", 0.04)], things
    if t < 85:
        return [], things
    if t < 90:
        return [_at(layout, 22, "masa-3")], []  # someone clears the table
    return [], []


SCENARIOS = {
    s.name: s
    for s in (
        Scenario("unattended", 105, _unattended, ("demo-unattended",)),
        Scenario("hand", 15, _hand, ("demo-hand",)),
        Scenario("queue", 40, _queue, ("demo-queue",)),
        Scenario("uncleared", 95, _uncleared, ("demo-uncleared",)),
    )
}


# -- fake ports ----------------------------------------------------------------------------


class ScenarioSource:
    """FrameSource: the scenario sampled at `fps` of simulated time, paced by `speed`."""

    def __init__(
        self,
        scenario: Scenario,
        fps: float = 5.0,
        speed: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        layout: Layout | None = None,
    ) -> None:
        self._scenario = scenario
        self._layout = layout or Layout.demo("cam-01")
        self._period = 1.0 / fps
        self._speed = speed
        self._sleep = sleep
        self._frames = int(scenario.duration_s * fps) + 1
        self._i = 0

    def read(self) -> tuple[float, Image] | None:
        if self._i >= self._frames:
            return None
        if self._i and self._speed > 0:
            self._sleep(self._period / self._speed)
        ts = self._i * self._period
        self._i += 1
        tracks, objects = self._scenario.script(ts, self._layout)
        return ts, Frame(ts=ts, tracks=tuple(tracks), objects=tuple(objects))


class EchoDetector:
    """PersonDetector: the scripted Frame is the detection. Its `raised_hand` flags only
    steer ScriptedPose; the pipeline recomputes them from keypoints."""

    def detect(self, image: Image, ts: float) -> Frame:
        assert isinstance(image, Frame)
        return image


def _raised() -> list[Keypoint]:
    kps: list[Keypoint] = [(0.5, 0.5, 0.0)] * 17
    kps[0] = (0.5, 0.30, 0.9)
    kps[5], kps[6] = (0.45, 0.40, 0.9), (0.55, 0.40, 0.9)
    kps[9], kps[10] = (0.45, 0.20, 0.9), (0.55, 0.50, 0.9)
    return kps


def _lowered() -> list[Keypoint]:
    kps = _raised()
    kps[9] = (0.45, 0.55, 0.9)
    return kps


class ScriptedPose:
    """PoseEstimator: keypoints with a raised wrist for tracks the script marked."""

    def estimate(self, image: Image, tracks: Sequence[TrackObs]) -> dict[int, list[Keypoint]]:
        return {t.track_id: _raised() if t.raised_hand else _lowered() for t in tracks}


class FallbackConfig:
    """ConfigSource: the run's layout camera, and the retained rules for it when there are
    any, else the demo rules. The camera is fixed for the run: the scenario's people are
    placed in its zones."""

    def __init__(
        self,
        primary: ConfigSource | None,
        camera_id: str,
        force_demo: bool,
        layout: Layout | None = None,
    ) -> None:
        self._primary = None if force_demo else primary
        self.layout = layout or Layout.demo(camera_id)
        self._camera_id = self.layout.camera.id
        self._demo_rules = demo_rules(self._camera_id)
        self._said: set[str] = set()

    def _say(self, key: str, msg: str) -> None:
        if key not in self._said:
            self._said.add(key)
            print(msg, flush=True)

    def rules(self) -> list[Rule]:
        retained = self._primary.rules() if self._primary else []
        mine = [r for r in retained if r.camera_id == self._camera_id]
        if mine:
            self._say("rules", f"fake_edge: using {len(mine)} retained rule(s) from MQTT")
            return retained
        self._say("rules", "fake_edge: no retained rules for this camera, using DEMO rules")
        return self._demo_rules

    def camera(self) -> CameraConfig:
        return self.layout.camera


class Recorder:
    """EventPublisher that keeps what it was given and forwards to `inner` (if any)."""

    def __init__(self, inner: EventPublisher | None = None) -> None:
        self.inner = inner
        self.alerts: list[AlertEvent] = []
        self.suggestions: list[StaffSuggestion] = []
        self.metrics: list[Metrics] = []

    def publish_alert(self, event: AlertEvent, snapshot_jpeg: bytes | None) -> None:
        self.alerts.append(event)
        if self.inner:
            self.inner.publish_alert(event, snapshot_jpeg)

    def publish_suggestion(self, suggestion: StaffSuggestion, snapshot_jpeg: bytes | None) -> None:
        self.suggestions.append(suggestion)
        if self.inner:
            self.inner.publish_suggestion(suggestion, snapshot_jpeg)

    def publish_metrics(self, metrics: Metrics) -> None:
        self.metrics.append(metrics)
        if self.inner:
            self.inner.publish_metrics(metrics)

    def publish_detections(self, detections: Detections) -> None:
        if self.inner:
            self.inner.publish_detections(detections)


def wall_clock(_ts: float) -> datetime:
    return datetime.now(UTC)


def run_scenario(
    scenario: Scenario,
    publisher: EventPublisher | None,
    config: ConfigSource,
    *,
    device: str,
    camera_id: str,
    speed: float = 1.0,
    fps: float = 5.0,
    stop: threading.Event | None = None,
    sleep: Callable[[float], None] = time.sleep,
    layout: Layout | None = None,
) -> Recorder:
    if layout is None:
        layout = config.layout if isinstance(config, FallbackConfig) else Layout.demo(camera_id)
    recorder = Recorder(publisher)
    pipeline = EdgePipeline(
        ScenarioSource(scenario, fps=fps, speed=speed, sleep=sleep, layout=layout),
        EchoDetector(),
        recorder,
        config,
        device=device,
        camera_id=camera_id,
        pose=ScriptedPose(),
        grace_s=1.5,
        to_datetime=wall_clock,
        id_factory=lambda: str(uuid.uuid4()),
    )
    pipeline.run(stop)
    return recorder


# -- CLI -------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--scenario", choices=sorted(SCENARIOS), default="unattended")
    p.add_argument("--speed", type=float, default=1.0, help="time compression (10 = 10x)")
    p.add_argument("--fps", type=float, default=5.0, help="simulated frames per second")
    p.add_argument("--camera-id", default=None, help="camera id (default: CAMERA_ID or cam-01)")
    p.add_argument("--demo", action="store_true", help="ignore retained rules/zones")
    p.add_argument("--retained-wait", type=float, default=1.5, help="seconds to wait for config")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from aivee_edge.app import build_client
    from aivee_edge.settings import EdgeSettings

    overrides = {"camera_id": args.camera_id} if args.camera_id else {}
    settings = EdgeSettings(**overrides)
    client = build_client(settings)
    try:
        client.start()
    except TimeoutError as e:
        print(f"fake_edge: cannot reach MQTT at {settings.mqtt_host}:{settings.mqtt_port}: {e}")
        return 3
    time.sleep(args.retained_wait)  # let retained rules/config arrive

    retained = None if args.demo else pick_camera(client.device_config(), args.camera_id)
    if retained is None:
        print("fake_edge: no retained camera with zones, using DEMO zones (Masa 1-4, ...)")
        layout = Layout.demo(settings.camera_id)
    else:
        layout = Layout.from_camera(retained)
        print(f"fake_edge: using retained camera {retained.id} ({len(retained.zones)} zone(s))")
        if layout.missing_tags:
            print(f"fake_edge: no retained zone tagged {', '.join(layout.missing_tags)}: demo-*")
    camera_id = layout.camera.id

    scenario = SCENARIOS[args.scenario]
    print(
        f"fake_edge: scenario={scenario.name} site={settings.site} device={settings.device} "
        f"camera={camera_id} sim={scenario.duration_s:.0f}s speed={args.speed}x",
        flush=True,
    )
    stop = threading.Event()
    try:
        rec = run_scenario(
            scenario,
            client,
            FallbackConfig(client, camera_id, args.demo, layout=layout),
            device=settings.device,
            camera_id=camera_id,
            speed=args.speed,
            fps=args.fps,
            stop=stop,
            layout=layout,
        )
    except KeyboardInterrupt:
        stop.set()
        return 130
    finally:
        time.sleep(1.0)  # let QoS 1 publishes leave before the graceful disconnect
        client.stop()
    for ev in rec.alerts:
        zone = next((z for z in layout.camera.zones if z.id == ev.zone_id), None)
        print(
            f"fake_edge: {ev.state:7} event_id={ev.event_id} rule={ev.rule_id} "
            f"zone={ev.zone_id} ({zone.name if zone else '?'}) {ev.summary_ro}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
