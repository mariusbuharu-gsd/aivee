"""Vision eval on labelled real-camera clips: `make eval-vision` (see README.md).

Runs the edge pipeline offline on every `<clip>.json` label file in `--clips` (default
`recordings/eval/`): FileSource → YOLO + ByteTrack → pose → roles → situation engine,
with the label's camera zones and rules and no MQTT. The alerts it opens are matched to
the labels (`matcher.py`) and the run prints recall per rule kind and false alerts per
labelled hour. Zero clips is not an error: it says how to make some and exits 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from aivee_contracts.detections import Detections
from aivee_contracts.events import AlertEvent, Metrics, StaffSuggestion
from aivee_contracts.geometry import CameraConfig
from aivee_contracts.rules import Rule

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from matcher import ClipLabels, ClipResult, Produced, match, report, rule_kind, summarise  # noqa: E402

DEFAULT_CLIPS = ROOT / "recordings" / "eval"
DEFAULT_RULES = HERE / "default_rules.json"
VIDEO_SUFFIXES = (".mp4", ".mkv", ".avi", ".mov")
NO_LIVE_BOXES_S = 1e9


class Collector:
    """EventPublisher that keeps the opened alerts and drops everything else."""

    def __init__(self) -> None:
        self.opened: list[AlertEvent] = []

    def publish_alert(
        self, event: AlertEvent, snapshot_jpeg: bytes | None, before_jpeg: bytes | None = None
    ) -> None:
        if event.state == "opened":
            self.opened.append(event)

    def publish_suggestion(self, suggestion: StaffSuggestion, snapshot_jpeg: bytes | None) -> None:
        pass

    def publish_metrics(self, metrics: Metrics) -> None:
        pass

    def publish_detections(self, detections: Detections) -> None:
        pass


class StaticConfig:
    def __init__(self, camera: CameraConfig, rules: list[Rule]) -> None:
        self._camera = camera
        self._rules = rules

    def rules(self) -> list[Rule]:
        return list(self._rules)

    def camera(self) -> CameraConfig:
        return self._camera


def load_rules(raw: list[dict[str, Any]] | None, camera_id: str) -> list[Rule]:
    """The label's rules, or the default table/entrance rules, bound to `camera_id`."""
    data = raw if raw is not None else json.loads(DEFAULT_RULES.read_text())
    return [Rule.model_validate({**r, "camera_id": camera_id}) for r in data]


def find_labels(clips: Path) -> list[Path]:
    return sorted(clips.glob("*.json")) if clips.is_dir() else []


def video_for(label: Path, data: dict[str, Any]) -> Path:
    if "video" in data:
        return label.parent / data["video"]
    for suffix in VIDEO_SUFFIXES:
        if (candidate := label.with_suffix(suffix)).exists():
            return candidate
    raise FileNotFoundError(f'no video next to {label.name} (set "video" in the label)')


def run_clip(label: Path, args: argparse.Namespace) -> tuple[ClipResult, list[Produced]]:
    from aivee_edge.adapters.capture import FileSource
    from aivee_edge.adapters.clip_visual import InlineVisualScorer
    from aivee_edge.adapters.yolo import YoloDetector
    from aivee_edge.pipeline import EdgePipeline

    data = json.loads(label.read_text())
    camera = CameraConfig.model_validate({"source": "file", **data["camera"]})
    rules = load_rules(data.get("rules"), camera.id)
    labels = ClipLabels.from_json(data)
    fps = float(data.get("fps", args.fps))
    source = FileSource(video_for(label, data), fps)
    pose = None
    if args.pose and Path(args.pose).exists():
        from aivee_edge.adapters.pose import PoseEstimator

        pose = PoseEstimator(args.pose)
    publisher = Collector()
    pipeline = EdgePipeline(
        source,
        YoloDetector(args.detector, fps=fps),
        publisher,
        StaticConfig(camera, rules),
        device="eval",
        camera_id=camera.id,
        pose=pose,
        visual=InlineVisualScorer(),
        detections_interval_s=NO_LIVE_BOXES_S,
        grace_s=args.grace_s,
    )
    last_ts = 0.0
    while (step := pipeline.step()) is not None:
        last_ts = step.frame.ts
    duration = source.duration_s or last_ts
    close = getattr(source, "close", None)
    if callable(close):
        close()
    kinds = {r.id: rule_kind(r) for r in rules}
    produced = [Produced(kinds[e.rule_id], e.zone_id, e.at.timestamp()) for e in publisher.opened]
    return match(labels, produced, duration), produced


def _mmss(t: float) -> str:
    return f"{int(t) // 60:02d}:{int(t) % 60:02d}"


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--clips", type=Path, default=DEFAULT_CLIPS, help="folder of clips + labels")
    p.add_argument("--detector", default=str(ROOT / "models" / "yolo11n_int8_openvino_model"))
    p.add_argument("--pose", default=str(ROOT / "models" / "yolo11n-pose_int8_openvino_model"))
    p.add_argument("--fps", type=float, default=10.0, help="analysis fps (a label may override)")
    p.add_argument("--grace-s", type=float, default=5.0, help="engine grace, as GRACE_S")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    labels = find_labels(args.clips)
    if not labels:
        print(
            f"eval-vision: no labelled clips in {args.clips}. Record some with "
            "`make record-cams`, label them as in evals/vision/README.md, then run again."
        )
        return 0
    results: list[ClipResult] = []
    for label in labels:
        try:
            result, produced = run_clip(label, args)
        except (OSError, ValueError, KeyError) as e:
            print(f"eval-vision: {label.name}: {e}", file=sys.stderr)
            return 2
        results.append(result)
        print(
            f"{label.stem}: {result.duration_s / 60:.1f} min, {len(produced)} alerts, "
            f"{len(result.hits)} hits, {len(result.misses)} missed, "
            f"{len(result.false_alerts)} false, {len(result.repeats)} repeats"
        )
        for p in result.false_alerts:
            print(f"  false  {_mmss(p.t)} {p.kind} {p.zone}")
        for e in result.misses:
            print(f"  missed {_mmss(e.t_start)}-{_mmss(e.t_end)} {e.kind} {e.zone or '*'}")
    print()
    print(report(summarise(results)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
