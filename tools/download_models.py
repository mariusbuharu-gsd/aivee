"""Download edge models into models/ and export YOLO to OpenVINO for fast CPU inference.

uv run python tools/download_models.py [--skip-export] [--no-int8]
    [--calib-data coco128.yaml] [--calib-pose-data coco8-pose.yaml]
    [--calib-frames DIR | --calib-clips CLIP ...] [--force-int8]

INT8 (NNCF) needs calibration images. By default the detector calibrates on coco128
(128 images) and pose on coco8-pose (8; the next public pose set, coco-pose, is ~20 GB),
both downloaded by ultralytics. Better: the venue's own cameras. `--calib-frames DIR`
uses a folder of JPEG/PNG frames (no labels needed); `--calib-clips` samples one frame
every `--calib-every-s` seconds from recorded clips first (`make record-cams`). An
existing INT8 export is kept unless `--force-int8`. See docs/handbook/edge-modes.md,
"INT8 calibration on venue frames".
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
YOLO_WEIGHTS = ("yolo11n.pt", "yolo11n-pose.pt")
DETECT_CALIB = "coco128.yaml"
POSE_CALIB = "coco8-pose.yaml"
"""Defaults: ultralytics downloads both. coco128 is 128 images; coco8-pose is the only
small public pose set (coco-pose is ~20 GB), so calibrate pose on venue frames."""
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}
COCO_KPT_FLIP = [0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15]
YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)


def is_pose(weights: str) -> bool:
    return "-pose" in weights


def calibration_for(weights: str, args: argparse.Namespace) -> str:
    """The dataset YAML (name or path) that calibrates `weights`, from the CLI options."""
    return str(args.calib_pose_data if is_pose(weights) else args.calib_data)


def frames_dataset(frames: Path, names: Mapping[int, str], *, pose: bool, out: Path) -> Path:
    """Write an ultralytics dataset YAML over a folder of unlabelled frames.

    Calibration only needs images: frames without a label file load as background.
    """
    images = [p for p in frames.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES]
    if not images:
        raise ValueError(f"no images in {frames}")
    lines = [f"path: {frames.resolve()}", "train: .", "val: .", "names:"]
    lines += [f"  {i}: {name}" for i, name in sorted(names.items())]
    if pose:
        lines += ["kpt_shape: [17, 3]", f"flip_idx: {COCO_KPT_FLIP}"]
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"calib-{'pose' if pose else 'detect'}.yaml"
    target.write_text("\n".join(lines) + "\n")
    return target


def sample_clips(clips: Sequence[Path], out: Path, every_s: float = 2.0) -> int:
    """Save one frame every `every_s` seconds of each clip as JPEG into `out`."""
    import cv2

    out.mkdir(parents=True, exist_ok=True)
    written = 0
    for clip in clips:
        cap = cv2.VideoCapture(str(clip))
        if not cap.isOpened():
            raise OSError(f"cannot open {clip}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
        step = max(1, round(fps * every_s))
        index = 0
        try:
            while True:
                ok, image = cap.read()
                if not ok:
                    break
                if index % step == 0:
                    cv2.imwrite(str(out / f"{clip.stem}-{index:06d}.jpg"), image)
                    written += 1
                index += 1
        finally:
            cap.release()
    return written


def fetch_yolo(
    name: str,
    calib: str,
    export: bool,
    int8: bool,
    force: bool = False,
    frames: Path | None = None,
    workdir: Path | None = None,
) -> None:
    """`calib`: dataset YAML for INT8; `frames` (venue images) replaces it when given."""
    from ultralytics import YOLO

    target = MODELS / name
    if not target.exists():
        model = YOLO(name)  # ultralytics downloads into the current directory
        shutil.move(str(Path(model.ckpt_path)), target)
        print(f"downloaded {target}")
    else:
        print(f"ok {target}")
    if not export:
        return
    # dynamic=True: a 640x640 static graph letterboxes 4:3/16:9 frames and wastes ~25-45% compute
    variants: dict[str, dict[str, object]] = {f"{target.stem}_openvino_model": {"dynamic": True}}
    int8_dir = f"{target.stem}_int8_openvino_model"
    if int8:
        variants[int8_dir] = {"dynamic": True, "int8": True, "data": calib}
    for dirname, kwargs in variants.items():
        replace = force and dirname == int8_dir
        if (MODELS / dirname).exists() and not replace:
            print(f"ok {MODELS / dirname}")
            continue
        if dirname == int8_dir:
            if frames is not None:
                names = dict(YOLO(str(target)).names)
                out = workdir or Path(tempfile.mkdtemp(prefix="aivee-calib-"))
                kwargs["data"] = str(frames_dataset(frames, names, pose=is_pose(name), out=out))
            if replace:
                shutil.rmtree(MODELS / dirname, ignore_errors=True)
            print(f"calibrating {dirname} on {kwargs['data']}")
        exported = YOLO(str(target)).export(format="openvino", imgsz=640, **kwargs)
        print(f"exported {exported}")


def fetch_yunet() -> None:
    target = MODELS / Path(YUNET_URL).name
    if target.exists():
        print(f"ok {target}")
        return
    tmp = target.with_suffix(".part")
    urllib.request.urlretrieve(YUNET_URL, tmp)
    tmp.rename(target)
    print(f"downloaded {target}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--skip-export", action="store_true", help="no OpenVINO export")
    parser.add_argument("--no-int8", action="store_true", help="skip INT8 (NNCF) export")
    parser.add_argument(
        "--calib-data", default=DETECT_CALIB, help=f"detector INT8 dataset (default {DETECT_CALIB})"
    )
    parser.add_argument(
        "--calib-pose-data", default=POSE_CALIB, help=f"pose INT8 dataset (default {POSE_CALIB})"
    )
    venue = parser.add_mutually_exclusive_group()
    venue.add_argument(
        "--calib-frames", type=Path, help="folder of venue frames: calibrates both models"
    )
    venue.add_argument(
        "--calib-clips", type=Path, nargs="+", help="venue clips to sample frames from"
    )
    parser.add_argument(
        "--calib-every-s", type=float, default=2.0, help="seconds between sampled clip frames"
    )
    parser.add_argument(
        "--force-int8",
        dest="force",
        action="store_true",
        help="re-export the INT8 models even if they exist (after changing calibration data)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    MODELS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aivee-calib-") as tmp:
        frames: Path | None = args.calib_frames
        if args.calib_clips:
            frames = Path(tmp) / "frames"
            count = sample_clips(args.calib_clips, frames, args.calib_every_s)
            print(f"sampled {count} calibration frames from {len(args.calib_clips)} clips")
        for name in YOLO_WEIGHTS:
            fetch_yolo(
                name,
                calibration_for(name, args),
                export=not args.skip_export,
                int8=not args.no_int8,
                force=args.force,
                frames=frames,
                workdir=Path(tmp),
            )
    fetch_yunet()


if __name__ == "__main__":
    main()
