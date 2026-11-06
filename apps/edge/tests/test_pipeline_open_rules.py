"""Open rules through the EdgePipeline: whole-frame pseudo-zone, detector classes, visual
scoring on the frame image, snapshots on open."""

from collections.abc import Iterator, Sequence
from itertools import count

from aivee_contracts.events import AlertEvent
from aivee_contracts.geometry import CameraConfig, Zone
from aivee_contracts.rules import ANYWHERE_TAG, Action, Condition, Rule
from aivee_edge.domain.observation import Frame, ObjectObs
from aivee_edge.domain.ports import Image
from aivee_edge.domain.visual import VisualJob, VisualSample
from aivee_edge.pipeline import EdgePipeline, extra_classes

CAM = "cam-01"
TABLE = Zone(id="t1", name="Masa 1", tag="table", polygon=[(0.1, 0.1), (0.4, 0.1), (0.4, 0.4)])


def rule(rule_id: str, tag: str, *conds: Condition, enabled: bool = True) -> Rule:
    return Rule(
        id=rule_id,
        camera_id=CAM,
        name=rule_id,
        prompt_ro="...",
        zone_tag=tag,
        all_of=list(conds),
        action=Action(type="telegram"),
        cooldown_s=120,
        enabled=enabled,
    )


BEAR = rule("bear", ANYWHERE_TAG, Condition(kind="object_present", objects=["bear"]))
FIRE = rule(
    "fire",
    ANYWHERE_TAG,
    Condition(
        kind="visual", positive=["fire"], negative=["room"], min_duration_s=1, label_ro="foc"
    ),
)


class ScriptSource:
    """Yields (ts, frame); the 'image' is the scripted Frame itself."""

    def __init__(self, frames: Sequence[Frame]) -> None:
        self._frames = iter(frames)

    def read(self) -> tuple[float, Image] | None:
        frame = next(self._frames, None)
        return None if frame is None else (frame.ts, frame)


class Recorder:
    def __init__(self) -> None:
        self.alerts: list[tuple[AlertEvent, bytes | None]] = []

    def publish_alert(
        self, event: AlertEvent, snapshot_jpeg: bytes | None, before_jpeg: bytes | None = None
    ) -> None:
        self.alerts.append((event, snapshot_jpeg))

    def publish_suggestion(self, suggestion: object, snapshot_jpeg: bytes | None) -> None:
        pass

    def publish_metrics(self, metrics: object) -> None:
        pass

    def publish_detections(self, detections: object) -> None:
        pass


class Config:
    def __init__(self, rules: list[Rule]) -> None:
        self.rules_ = rules

    def rules(self) -> list[Rule]:
        return list(self.rules_)

    def camera(self) -> CameraConfig:
        return CameraConfig(id=CAM, name="Sala principală", source="0", zones=[TABLE])


class ClassDetector:
    """Echoes the scripted frame and records the extra classes it was asked for."""

    def __init__(self) -> None:
        self.extra: list[list[str]] = []

    def detect(self, image: Image, ts: float) -> Frame:
        assert isinstance(image, Frame)
        return image

    def set_extra_classes(self, extra: Sequence[str]) -> None:
        self.extra.append(list(extra))


class Scorer:
    def __init__(self) -> None:
        self.images: list[object] = []

    def prepare(self, prompts: Sequence[str]) -> None:
        pass

    def submit(self, ts: float, image: Image, jobs: Sequence[VisualJob]) -> bool:
        self.images.append(image)
        self._done = [VisualSample(ts, j.key, 0.9) for j in jobs]
        return True

    def collect(self) -> list[VisualSample]:
        done, self._done = getattr(self, "_done", []), []
        return done


class Snapshots:
    def make(self, image: Image) -> bytes | None:
        return b"jpeg"

    def crop(self, image: Image, bbox: object) -> bytes | None:
        return None


def pipeline(
    frames: Sequence[Frame], rules: list[Rule], rec: Recorder, **kw: object
) -> EdgePipeline:
    ids: Iterator[int] = count(1)
    return EdgePipeline(
        ScriptSource(frames),
        kw.pop("detector", ClassDetector()),  # type: ignore[arg-type]
        rec,
        Config(rules),
        device="edge-01",
        camera_id=CAM,
        id_factory=lambda: f"id{next(ids)}",
        cpu=lambda: 0.0,
        snapshots=Snapshots(),
        grace_s=1.0,
        **kw,  # type: ignore[arg-type]
    )


def test_bear_anywhere_opens_on_the_pseudo_zone_with_a_snapshot() -> None:
    bear = ObjectObs("bear", (0.6, 0.5, 0.9, 1.0))
    frames = [Frame(ts=k / 10, objects=(bear,)) for k in range(5)]
    rec = Recorder()
    detector = ClassDetector()
    p = pipeline(frames, [BEAR], rec, detector=detector)
    p.run()
    assert [(e.state, e.zone_id, e.summary_ro, snap) for e, snap in rec.alerts] == [
        ("opened", ANYWHERE_TAG, "Sala principală: a apărut un urs", b"jpeg")
    ]
    assert detector.extra == [["bear"]]
    assert [z.id for z in p.zones] == ["t1", ANYWHERE_TAG]


def test_no_pseudo_zone_and_no_extra_classes_without_open_rules() -> None:
    present = rule("p", "table", Condition(kind="present", role="guest"))
    detector = ClassDetector()
    p = pipeline([Frame(ts=0.0)], [present], Recorder(), detector=detector)
    p.run()
    assert [z.id for z in p.zones] == ["t1"] and detector.extra == [[]]


def test_visual_rule_scores_the_frame_image_and_opens() -> None:
    frames = [Frame(ts=k / 10) for k in range(15)]
    rec = Recorder()
    scorer = Scorer()
    p = pipeline(frames, [FIRE], rec, visual=scorer, visual_hz=2.0)
    p.run()
    assert [(e.state, e.summary_ro, e.at.timestamp()) for e, _ in rec.alerts] == [
        ("opened", "Sala principală: posibil foc", 1.0)
    ]
    assert scorer.images == [frames[0], frames[5], frames[10]]


def test_extra_classes_come_from_enabled_object_present_rules_only() -> None:
    off = rule(
        "off", ANYWHERE_TAG, Condition(kind="object_present", objects=["dog"]), enabled=False
    )
    knife = rule("k", "table", Condition(kind="object_present", objects=["knife", "bear"]))
    assert extra_classes([BEAR, off, knife, FIRE]) == ["bear", "knife"]
