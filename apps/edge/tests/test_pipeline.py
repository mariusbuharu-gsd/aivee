"""EdgePipeline with every port faked: scripted frames in, published calls out."""

from collections.abc import Iterator, Mapping, Sequence
from itertools import count

import pytest
from aivee_contracts.commands import EdgeCommand
from aivee_contracts.detections import Detections
from aivee_contracts.events import AlertEvent, Metrics, StaffProfile, StaffProfiles, StaffSuggestion
from aivee_contracts.geometry import CameraConfig, Zone
from aivee_contracts.rules import Action, Condition, Rule
from aivee_edge.domain.observation import BBox, Frame, ObjectObs, TrackObs
from aivee_edge.domain.ports import Image
from aivee_edge.domain.pose import Keypoint
from aivee_edge.pipeline import EdgePipeline, StepResult

CAM = "cam-01"


def square(x: float, y: float, size: float = 0.25) -> list[tuple[float, float]]:
    return [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]


def centre(zone: Zone) -> tuple[float, float]:
    xs = [p[0] for p in zone.polygon]
    ys = [p[1] for p in zone.polygon]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def box_at(x: float, y: float) -> BBox:
    """A person box whose foot point is (x, y)."""
    return (x - 0.03, y - 0.15, x + 0.03, y)


def at(zone: Zone) -> BBox:
    return box_at(*centre(zone))


T1 = Zone(id="t1", name="Masa 1", tag="table", polygon=square(0.05, 0.05))
T2 = Zone(id="t2", name="Masa 2", tag="table", polygon=square(0.70, 0.05))
T3 = Zone(id="t3", name="Masa 3", tag="table", polygon=square(0.05, 0.55))
T4 = Zone(id="t4", name="Masa 4", tag="table", polygon=square(0.70, 0.55))
KITCHEN = Zone(id="k", name="Bucătărie", tag="staff", polygon=square(0.40, 0.72))
ENTRANCE = Zone(id="e", name="Intrare", tag="entrance", polygon=square(0.40, 0.05, 0.2))
ZONES = [T1, T2, T3, T4, KITCHEN, ENTRANCE]


def rule(rule_id: str, tag: str, *conds: Condition, cooldown_s: int = 300) -> Rule:
    return Rule(
        id=rule_id,
        camera_id=CAM,
        name=rule_id,
        prompt_ro="...",
        zone_tag=tag,
        all_of=list(conds),
        action=Action(type="telegram"),
        cooldown_s=cooldown_s,
    )


UNATTENDED = rule(
    "unattended",
    "table",
    Condition(kind="present", role="guest", min_duration_s=60),
    Condition(kind="absent", role="staff", min_duration_s=60),
)
CALLS = rule("calls", "table", Condition(kind="pose", role="guest", pose="raised_hand"))


# -- fakes ---------------------------------------------------------------------------


class ScriptSource:
    """Yields (ts, frame); the 'image' is the scripted Frame itself."""

    def __init__(self, frames: Sequence[Frame]) -> None:
        self._frames = iter(frames)

    def read(self) -> tuple[float, Image] | None:
        frame = next(self._frames, None)
        return None if frame is None else (frame.ts, frame)


class EchoDetector:
    def detect(self, image: Image, ts: float) -> Frame:
        assert isinstance(image, Frame)
        return image


class Recorder:
    def __init__(self) -> None:
        self.alerts: list[tuple[AlertEvent, bytes | None]] = []
        self.suggestions: list[StaffSuggestion] = []
        self.suggestions_with_snapshots: list[tuple[StaffSuggestion, bytes | None]] = []
        self.metrics: list[Metrics] = []
        self.detections: list[Detections] = []

    def publish_alert(self, event: AlertEvent, snapshot_jpeg: bytes | None) -> None:
        self.alerts.append((event, snapshot_jpeg))

    def publish_suggestion(self, suggestion: StaffSuggestion, snapshot_jpeg: bytes | None) -> None:
        self.suggestions.append(suggestion)
        self.suggestions_with_snapshots.append((suggestion, snapshot_jpeg))

    def publish_metrics(self, metrics: Metrics) -> None:
        self.metrics.append(metrics)

    def publish_detections(self, detections: Detections) -> None:
        self.detections.append(detections)

    def states(self) -> list[tuple[str, str, str]]:
        return [(e.state, e.rule_id, e.zone_id) for e, _ in self.alerts]


class Config:
    def __init__(self, rules: list[Rule], zones: list[Zone]) -> None:
        self.rules_ = rules
        self.zones_ = zones

    def rules(self) -> list[Rule]:
        return list(self.rules_)

    def camera(self) -> CameraConfig:
        return CameraConfig(id=CAM, name="Sala", source="0", zones=self.zones_)


def raised_keypoints() -> list[Keypoint]:
    kps: list[Keypoint] = [(0.5, 0.5, 0.0)] * 17
    kps[0] = (0.5, 0.30, 0.9)  # nose
    kps[5], kps[6] = (0.45, 0.40, 0.9), (0.55, 0.40, 0.9)  # shoulders
    kps[9], kps[10] = (0.45, 0.20, 0.9), (0.55, 0.50, 0.9)  # left wrist up
    return kps


class RaisingPose:
    def __init__(self) -> None:
        self.calls: list[list[int]] = []

    def estimate(self, image: Image, tracks: Sequence[TrackObs]) -> Mapping[int, list[Keypoint]]:
        self.calls.append([t.track_id for t in tracks])
        return {t.track_id: raised_keypoints() for t in tracks}


def pipeline(
    frames: Sequence[Frame], config: Config, rec: Recorder, **kwargs: object
) -> EdgePipeline:
    ids: Iterator[int] = count(1)
    return EdgePipeline(
        ScriptSource(frames),
        EchoDetector(),
        rec,
        config,
        device="edge-01",
        camera_id=CAM,
        id_factory=lambda: f"id{next(ids)}",
        cpu=lambda: 0.0,
        **kwargs,  # type: ignore[arg-type]
    )


def guests(ts: float) -> tuple[TrackObs, ...]:
    x, y = centre(T1)
    return (
        TrackObs(track_id=1, bbox=box_at(x - 0.04, y)),
        TrackObs(track_id=2, bbox=box_at(x + 0.04, y)),
    )


def walker_position(t: float) -> tuple[float, float]:
    """Loops Masa 2 → Masa 4 → kitchen → Masa 3 → kitchen → Masa 4, never Masa 1."""
    stops = [centre(z) for z in (T2, T4, KITCHEN, T3, KITCHEN, T4)]
    leg_s = 4.0
    leg = int(t // leg_s) % len(stops)
    a, b = stops[leg], stops[(leg + 1) % len(stops)]
    f = (t % leg_s) / leg_s
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


# -- tests ---------------------------------------------------------------------------


def test_unattended_table_arrives_then_closes_when_staff_like_walker_stays() -> None:
    frames = []
    for ts in range(0, 121):
        tracks = list(guests(ts))
        if 5 <= ts < 100:
            tracks.append(TrackObs(track_id=7, bbox=box_at(*walker_position(ts - 5))))
        elif ts >= 100:
            tracks.append(TrackObs(track_id=7, bbox=at(T1)))  # the waiter comes to Masa 1
        frames.append(Frame(ts=float(ts), tracks=tuple(tracks)))
    rec = Recorder()
    p = pipeline(frames, Config([UNATTENDED], ZONES), rec)
    p.run()

    assert rec.states() == [
        ("opened", "unattended", "t1"),
        ("arrived", "unattended", "t1"),
        ("closed", "unattended", "t1"),
    ]
    opened, arrived, closed = (e for e, _ in rec.alerts)
    assert opened.at.timestamp() == 60
    assert opened.summary_ro == "Masa 1: neservită de 1 min"
    # The waiter reaches Masa 1 at 100 and has stayed ARRIVE_S (5 s) at 105.
    assert arrived.at.timestamp() == closed.at.timestamp() == 105
    assert rec.alerts[1][1] is None  # no snapshot for arrived
    assert [s.track_id for s in rec.suggestions] == [7]


def test_raised_hand_counts_only_inside_table_zones() -> None:
    at_table = TrackObs(track_id=1, bbox=at(T2))
    at_door = TrackObs(track_id=2, bbox=at(ENTRANCE))
    frames = [Frame(ts=0.0, tracks=(at_door,)), Frame(ts=1.0, tracks=(at_table, at_door))]
    rec, pose = Recorder(), RaisingPose()
    p = pipeline(frames, Config([CALLS], ZONES), rec, pose=pose)

    first = p.step()
    assert first is not None and first.verified is False  # nobody at a table: pose skipped
    assert first.frame.tracks[0].raised_hand is False
    second = p.step()
    assert second is not None and second.verified is True
    assert pose.calls == [[1]]
    hands = {t.track_id: t.raised_hand for t in second.frame.tracks}
    assert hands == {1: True, 2: False}
    assert rec.states() == [("opened", "calls", "t2")]


def test_metrics_are_published_every_interval() -> None:
    frames = [Frame(ts=i / 10, tracks=(TrackObs(1, at(T1)),)) for i in range(0, 111)]
    rec = Recorder()
    p = pipeline(frames, Config([], ZONES), rec, pose=RaisingPose())
    p.run()
    assert len(rec.metrics) == 2
    m = rec.metrics[0]
    assert (m.device, m.fps, m.verified_ratio, m.cpu_percent) == ("edge-01", 10.0, 1.0, 0.0)


def test_hot_reload_of_rules_and_zones() -> None:
    hand = TrackObs(track_id=1, bbox=at(T2))
    frames = [Frame(ts=float(t), tracks=(hand,)) for t in range(4)]
    config = Config([], [T1])
    rec = Recorder()
    p = pipeline(frames, config, rec, pose=RaisingPose())

    p.step()  # no rules, no Masa 2
    config.rules_ = [CALLS]
    p.step()  # rule active, but Masa 2 is not a zone yet
    assert rec.alerts == []
    config.zones_ = [T1, T2]
    p.step()
    assert rec.states() == [("opened", "calls", "t2")]
    assert [z.id for z in p.zones] == ["t1", "t2"]
    config.rules_ = []
    p.step()
    assert rec.states()[-1] == ("closed", "calls", "t2")


def test_tracks_that_disappear_are_forgotten() -> None:
    frames = [Frame(ts=float(t), tracks=(TrackObs(5, at(T3)),)) for t in range(3)]
    frames += [Frame(ts=float(t)) for t in range(3, 10)]
    p = pipeline(frames, Config([], ZONES), Recorder(), forget_after_s=5.0)
    for _ in range(3):
        p.step()
    assert p.tracked_ids() == {5}
    assert p.buffer.samples(5)
    p.run()
    assert p.tracked_ids() == set()
    assert p.buffer.samples(5) == []


class CountingEmbedder:
    def __init__(self) -> None:
        self.calls = 0

    def embed(self, image: Image, bbox: BBox) -> list[float]:
        self.calls += 1
        return [1.0, 0.0]


def test_appearance_runs_only_with_profiles_and_at_most_every_interval() -> None:
    frames = [Frame(ts=t / 2, tracks=(TrackObs(1, at(T1)),)) for t in range(10)]  # 0 .. 4.5 s
    embedder = CountingEmbedder()
    profiles: list[StaffProfiles | None] = [None]

    p = pipeline(
        frames, Config([], ZONES), Recorder(), embedder=embedder, profiles=lambda: profiles[0]
    )
    p.step()
    assert embedder.calls == 0
    profiles[0] = StaffProfiles(
        device="edge-01", profiles=[StaffProfile(id="p", name="Ospătar", centroid=[1.0, 0.0])]
    )
    result = p.step()  # ts 0.5: first embed
    assert result is not None and result.verified
    assert result.frame.tracks[0].staff_score == 0.5  # appearance 1.0, behaviour 0.0
    p.run()  # ts 1.0 .. 4.5: embeds again at 2.5 and 4.5
    assert embedder.calls == 3


def test_appearance_thresholds_are_passed_to_the_score() -> None:
    frames = [Frame(ts=0.0, tracks=(TrackObs(1, at(T1)),))]
    profiles = StaffProfiles(
        device="edge-01", profiles=[StaffProfile(id="p", name="Ospătar", centroid=[0.5, 0.0])]
    )
    p = pipeline(
        frames,
        Config([], ZONES),
        Recorder(),
        embedder=CountingEmbedder(),
        profiles=lambda: profiles,
        appearance_low=0.9,
        appearance_high=0.95,
    )
    p.run()
    assert p.appearance_of(1) == 1.0  # cosine 1.0 >= high
    lower = pipeline(
        frames,
        Config([], ZONES),
        Recorder(),
        embedder=CountingEmbedder(),
        profiles=lambda: StaffProfiles(
            device="edge-01",
            profiles=[StaffProfile(id="p", name="Ospătar", centroid=[0.76, 0.6499230723708769])],
        ),
    )
    lower.run()
    assert lower.appearance_of(1) == pytest.approx(0.5)  # cosine 0.76 with defaults 0.70-0.82


class FakeSnapshots:
    def __init__(self) -> None:
        self.crops: list[BBox] = []

    def make(self, image: Image) -> bytes | None:
        return b"jpeg"

    def crop(self, image: Image, bbox: BBox) -> bytes | None:
        self.crops.append(bbox)
        return b"crop"


def test_suggestion_carries_the_face_blurred_person_crop() -> None:
    frames = []
    for ts in range(0, 60):
        frames.append(Frame(ts=float(ts), tracks=(TrackObs(7, box_at(*walker_position(ts))),)))
    rec, snaps = Recorder(), FakeSnapshots()
    p = pipeline(frames, Config([], ZONES), rec, snapshots=snaps)
    p.run()
    assert [(s.track_id, snap) for s, snap in rec.suggestions_with_snapshots] == [(7, b"crop")]
    assert len(snaps.crops) == 1  # only when a suggestion is made, not every frame


def test_suggestion_without_snapshots_has_none() -> None:
    frames = [
        Frame(ts=float(t), tracks=(TrackObs(7, box_at(*walker_position(t))),)) for t in range(60)
    ]
    rec = Recorder()
    pipeline(frames, Config([], ZONES), rec).run()
    assert [snap for _, snap in rec.suggestions_with_snapshots] == [None]


def test_snapshot_only_for_opened_alerts() -> None:
    hand, still = TrackObs(1, at(T1)), TrackObs(1, at(T1))
    frames = [Frame(ts=0.0, tracks=(hand,)), Frame(ts=1.0, tracks=(still,))]

    class OnceRaising(RaisingPose):
        def estimate(
            self, image: Image, tracks: Sequence[TrackObs]
        ) -> Mapping[int, list[Keypoint]]:
            return super().estimate(image, tracks) if not self.calls else {}

    rec = Recorder()
    p = pipeline(frames, Config([CALLS], ZONES), rec, pose=OnceRaising(), snapshots=FakeSnapshots())
    p.run()
    assert [(e.state, snap) for e, snap in rec.alerts] == [("opened", b"jpeg"), ("closed", None)]


# -- owner commands ------------------------------------------------------------------


class FakeCommands:
    def __init__(self) -> None:
        self.pending: list[EdgeCommand] = []

    def take_commands(self) -> list[EdgeCommand]:
        out, self.pending = self.pending, []
        return out


def command(kind: str, track_id: int, *, camera_id: str = CAM, command_id: str = "") -> EdgeCommand:
    return EdgeCommand.model_validate(
        {
            "command_id": command_id or f"{kind}-{track_id}",
            "kind": kind,
            "camera_id": camera_id,
            "track_id": track_id,
            "suggestion_id": "s1",
            "at": "2026-11-06T12:00:00Z",
        }
    )


def roles(result: object) -> dict[int, tuple[str, float]]:
    assert isinstance(result, StepResult)
    return {t.track_id: (t.role, t.staff_score) for t in result.frame.tracks}


def test_owner_confirm_and_reject_override_the_role() -> None:
    frames = [Frame(ts=float(t), tracks=(TrackObs(1, at(T1)),)) for t in range(4)]
    commands = FakeCommands()
    p = pipeline(frames, Config([], ZONES), Recorder(), commands=commands)

    assert roles(p.step()) == {1: ("guest", 0.0)}
    commands.pending = [command("confirm_staff", 1)]
    assert roles(p.step()) == {1: ("staff", 1.0)}
    commands.pending = [command("reject_staff", 1)]
    assert roles(p.step()) == {1: ("guest", 0.0)}


def test_commands_for_other_cameras_unknown_tracks_or_seen_twice_are_ignored() -> None:
    frames = [Frame(ts=float(t), tracks=(TrackObs(1, at(T1)),)) for t in range(4)]
    frames.append(Frame(ts=4.0, tracks=(TrackObs(1, at(T1)), TrackObs(42, at(T2)))))
    commands = FakeCommands()
    p = pipeline(frames, Config([], ZONES), Recorder(), commands=commands)
    p.step()
    commands.pending = [
        command("confirm_staff", 1, camera_id="cam-99"),
        command("confirm_staff", 42),  # not tracked (yet): dropped, not remembered
    ]
    assert roles(p.step()) == {1: ("guest", 0.0)}

    commands.pending = [command("confirm_staff", 1, command_id="c1")]
    p.step()
    commands.pending = [command("reject_staff", 1, command_id="c1")]  # redelivered id
    assert roles(p.step()) == {1: ("staff", 1.0)}
    assert roles(p.step())[42][0] == "guest"


# -- live detections -----------------------------------------------------------------


def test_detections_are_published_at_most_five_times_a_second() -> None:
    frames = [Frame(ts=i / 10, tracks=(TrackObs(1, at(T1)),)) for i in range(20)]  # 10 fps, 2 s
    rec = Recorder()
    pipeline(frames, Config([], ZONES), rec).run()
    stamps = [d.ts.timestamp() for d in rec.detections]
    assert stamps == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8]


def test_detections_carry_roles_hands_and_objects_with_clamped_boxes() -> None:
    hand = TrackObs(1, at(T2))
    edge_of_frame = TrackObs(2, (-0.01, 0.5, 0.1, 1.0004))
    cup = ObjectObs("cup", (0.1, 0.1, 0.12, 0.13), confidence=0.9)
    frames = [Frame(ts=0.0, tracks=(hand, edge_of_frame), objects=(cup,))]
    commands = FakeCommands()
    rec = Recorder()
    p = pipeline(frames, Config([], ZONES), rec, pose=RaisingPose(), commands=commands)
    p.run()

    [d] = rec.detections
    assert d.camera_id == CAM
    by_id = {t.track_id: t for t in d.tracks}
    assert by_id[1].raised_hand is True and by_id[1].role == "guest"
    assert by_id[1].bbox == hand.bbox
    assert by_id[2].bbox == (0.0, 0.5, 0.1, 1.0)
    assert [(o.label, o.bbox) for o in d.objects] == [("cup", cup.bbox)]
