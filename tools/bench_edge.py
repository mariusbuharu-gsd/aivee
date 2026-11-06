"""Measure edge CPU throughput: detector (+tracker) and pose, torch vs OpenVINO.

uv run python tools/bench_edge.py --source sample            # synthetic clip from bus.jpg
uv run python tools/bench_edge.py --source clip.mp4 --seconds 20
uv run python tools/bench_edge.py --source 0                 # webcam
uv run python tools/bench_edge.py --source http://PHONE:8080/video
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2
import numpy as np
from aivee_edge.adapters.capture import Cv2Source, FileSource
from aivee_edge.adapters.pose import PoseEstimator
from aivee_edge.adapters.yolo import YoloDetector

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
BACKENDS = {
    "torch": ("yolo11n.pt", "yolo11n-pose.pt"),
    "openvino": ("yolo11n_openvino_model", "yolo11n-pose_openvino_model"),
    "ov-int8": ("yolo11n_int8_openvino_model", "yolo11n-pose_int8_openvino_model"),
}


def make_sample(path: Path, seconds: int = 10, fps: int = 25) -> Path:
    """Synthetic 640x480 clip: ultralytics' bus.jpg (4 people) slowly panning."""
    import ultralytics

    src = cv2.imread(str(Path(ultralytics.__file__).parent / "assets" / "bus.jpg"))
    w = src.shape[1]  # bus.jpg is 810 wide x 1080 high
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (640, 480))
    n = seconds * fps
    for i in range(n):
        dx = int((w - 640 * 1.2) * (0.5 + 0.5 * np.sin(2 * np.pi * i / n)))
        crop = src[: int(480 * 1.6), dx : dx + int(640 * 1.2)]
        writer.write(cv2.resize(crop, (640, 480)))
    writer.release()
    return path


def open_source(spec: str) -> Cv2Source | FileSource:
    if spec == "sample":
        MODELS.mkdir(exist_ok=True)
        clip = MODELS / "sample_bus.mp4"
        if not clip.exists():
            make_sample(clip)
        return FileSource(clip, target_fps=0, loop=True)
    if Path(spec).exists():
        return FileSource(spec, target_fps=0, loop=True)
    return Cv2Source(spec, target_fps=0)


def bench(
    source_spec: str, backend: str, with_pose: bool, seconds: float, imgsz: int
) -> tuple[float, float, int]:
    det_name, pose_name = BACKENDS[backend]
    detector = YoloDetector(MODELS / det_name, imgsz=imgsz)
    pose = PoseEstimator(MODELS / pose_name, imgsz=imgsz) if with_pose else None
    source = open_source(source_spec)

    # warm-up (first OpenVINO inference compiles the graph)
    for _ in range(3):
        item = source.read()
        if item is None:
            raise SystemExit("source produced no frames")
        frame = detector.detect(item[1], item[0])
        if pose is not None:
            pose.estimate(item[1], frame.tracks)

    frames = 0
    tracks_seen = 0
    pose_time = 0.0
    start = time.perf_counter()
    while time.perf_counter() - start < seconds:
        item = source.read()
        if item is None:
            break
        ts, image = item
        frame = detector.detect(image, ts)
        tracks_seen += len(frame.tracks)
        if pose is not None:
            t0 = time.perf_counter()
            pose.estimate(image, frame.tracks)
            pose_time += time.perf_counter() - t0
        frames += 1
    elapsed = time.perf_counter() - start
    avg_tracks = tracks_seen / max(frames, 1)
    pose_ms = 1000 * pose_time / max(frames, 1)
    print(
        f"{backend:9s} {'det+pose' if with_pose else 'det':9s} {frames / elapsed:6.1f} FPS"
        f"  ({frames} frames / {elapsed:.1f}s, avg {avg_tracks:.1f} tracks"
        + (f", pose {pose_ms:.0f} ms/frame)" if with_pose else ")")
    )
    return frames / elapsed, pose_ms, frames


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="sample", help="file, webcam index, URL or 'sample'")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--backend", choices=[*BACKENDS, "all"], default="all")
    parser.add_argument("--no-pose", action="store_true")
    args = parser.parse_args()

    backends = list(BACKENDS) if args.backend == "all" else [args.backend]
    for backend in backends:
        bench(args.source, backend, False, args.seconds, args.imgsz)
        if not args.no_pose:
            bench(args.source, backend, True, args.seconds, args.imgsz)


if __name__ == "__main__":
    main()
