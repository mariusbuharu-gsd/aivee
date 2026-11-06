"""Fake edge device: scripted people through the REAL edge pipeline, published over MQTT.

No camera or models: a scenario yields synthetic Frames which go through EdgePipeline
(behaviour, roles, situation engine), so alerts are produced by the same code as on a
real device. Publishes as the edge MQTT user from .env.

    uv run python tools/fake_edge.py --scenario unattended --speed 10
    make fake-edge SCENARIO=hand

Scenarios (simulated seconds; --speed compresses wall time):
  unattended  two guests sit at Masa 1; nobody comes; alert opens at 60 s; a waiter who
              walks between the other tables and the kitchen comes to Masa 1 → closes
  hand        a guest at Masa 2 raises a hand → opens; hand down → closes
  queue       three guests wait at the entrance with no staff → opens; seated → closes
  uncleared   guests leave Masa 3 with cups on it → opens after 60 s; cleared → closes

Rules and zones come from the retained `rules`/`config` topics; when none are retained
(or with --demo) a built-in demo layout and rule set is used, and the script says so.
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

from aivee_contracts.events import AlertEvent, Metrics, StaffSuggestion
from aivee_contracts.geometry import CameraConfig, Zone
from aivee_contracts.rules import Action, Condition, Rule
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


# -- scenarios ---------------------------------------------------------------------------


def _centre(zone_id: str) -> tuple[float, float]:
    poly = ZONE[zone_id].polygon
    return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))


def _person(track_id: int, x: float, y: float, hand: bool = False) -> TrackObs:
    """A person whose feet are at (x, y); `hand` asks the scripted pose for a raised hand."""
    return TrackObs(track_id=track_id, bbox=(x - 0.03, y - 0.15, x + 0.03, y), raised_hand=hand)


def _at(track_id: int, zone_id: str, dx: float = 0.0, hand: bool = False) -> TrackObs:
    x, y = _centre(zone_id)
    return _person(track_id, x + dx, y, hand)


def _object(label: str, zone_id: str, dx: float = 0.0) -> ObjectObs:
    x, y = _centre(zone_id)
    box: BBox = (x + dx - 0.02, y - 0.04, x + dx + 0.02, y)
    return ObjectObs(label=label, bbox=box)


WAITER_ROUND = ["masa-2", "masa-4", "bucatarie", "masa-3", "bucatarie", "masa-4"]


def _walking(t: float, stops: Sequence[str], leg_s: float = 4.0) -> tuple[float, float]:
    leg = int(t // leg_s) % len(stops)
    a, b = _centre(stops[leg]), _centre(stops[(leg + 1) % len(stops)])
    f = (t % leg_s) / leg_s
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


@dataclass(frozen=True)
class Scenario:
    name: str
    duration_s: float
    script: Callable[[float], tuple[list[TrackObs], list[ObjectObs]]]
    expects: tuple[str, ...] = field(default=())
    """Rule ids whose alert should open (and close) with the demo rules."""


def _unattended(t: float) -> tuple[list[TrackObs], list[ObjectObs]]:
    tracks = [_at(1, "masa-1", -0.04), _at(2, "masa-1", 0.04)]
    if 5 <= t < 90:
        tracks.append(_person(7, *_walking(t - 5, WAITER_ROUND)))  # never at Masa 1
    elif t >= 90:
        tracks.append(_at(7, "masa-1"))  # the waiter finally comes to Masa 1
    return tracks, []


def _hand(t: float) -> tuple[list[TrackObs], list[ObjectObs]]:
    raised = 5 <= t < 10
    return [_at(3, "masa-2", hand=raised), _at(4, "masa-2", 0.05)], []


def _queue(t: float) -> tuple[list[TrackObs], list[ObjectObs]]:
    if t < 30:
        arrived = min(3, 1 + int(t // 3))
        return [_at(10 + i, "intrare", dx=(i - 1) * 0.05) for i in range(arrived)], []
    return [_at(10 + i, "masa-4", dx=(i - 1) * 0.05) for i in range(3)], []  # seated


def _uncleared(t: float) -> tuple[list[TrackObs], list[ObjectObs]]:
    if t < 15:
        return [_at(20, "masa-3", -0.04), _at(21, "masa-3", 0.04)], [
            _object("cup", "masa-3", -0.03),
            _object("bowl", "masa-3", 0.03),
        ]
    if t < 85:
        return [], [_object("cup", "masa-3", -0.03), _object("bowl", "masa-3", 0.03)]
    if t < 90:
        return [_at(22, "masa-3")], []  # someone clears the table
    return [], []


SCENARIOS = {
    s.name: s
    for s in (
        Scenario("unattended", 100, _unattended, ("demo-unattended",)),
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
    ) -> None:
        self._scenario = scenario
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
        tracks, objects = self._scenario.script(ts)
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
    """ConfigSource: retained rules/zones when there are any, else the demo set."""

    def __init__(self, primary: ConfigSource | None, camera_id: str, force_demo: bool) -> None:
        self._primary = None if force_demo else primary
        self._camera_id = camera_id
        self._demo_rules = demo_rules(camera_id)
        self._demo_camera = demo_camera(camera_id)
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
        if self._primary is not None:
            try:
                camera = self._primary.camera()
                if camera.zones:
                    self._say("zones", f"fake_edge: using {len(camera.zones)} retained zone(s)")
                    return camera
            except LookupError:
                pass
        self._say("zones", "fake_edge: no retained zones, using DEMO zones (Masa 1-4, ...)")
        return self._demo_camera


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

    def publish_suggestion(self, suggestion: StaffSuggestion) -> None:
        self.suggestions.append(suggestion)
        if self.inner:
            self.inner.publish_suggestion(suggestion)

    def publish_metrics(self, metrics: Metrics) -> None:
        self.metrics.append(metrics)
        if self.inner:
            self.inner.publish_metrics(metrics)


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
) -> Recorder:
    recorder = Recorder(publisher)
    pipeline = EdgePipeline(
        ScenarioSource(scenario, fps=fps, speed=speed, sleep=sleep),
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

    scenario = SCENARIOS[args.scenario]
    print(
        f"fake_edge: scenario={scenario.name} site={settings.site} device={settings.device} "
        f"camera={settings.camera_id} sim={scenario.duration_s:.0f}s speed={args.speed}x",
        flush=True,
    )
    stop = threading.Event()
    try:
        rec = run_scenario(
            scenario,
            client,
            FallbackConfig(client, settings.camera_id, args.demo),
            device=settings.device,
            camera_id=settings.camera_id,
            speed=args.speed,
            fps=args.fps,
            stop=stop,
        )
    except KeyboardInterrupt:
        stop.set()
        return 130
    finally:
        time.sleep(1.0)  # let QoS 1 publishes leave before the graceful disconnect
        client.stop()
    for ev in rec.alerts:
        print(f"fake_edge: {ev.state:6} event_id={ev.event_id} rule={ev.rule_id} {ev.summary_ro}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
