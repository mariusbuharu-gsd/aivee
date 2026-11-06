"""Download edge models into models/ and export YOLO to OpenVINO for fast CPU inference.

uv run python tools/download_models.py [--skip-export]
"""

from __future__ import annotations

import argparse
import shutil
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
# weights -> INT8 calibration dataset (tiny, auto-downloaded by ultralytics)
YOLO_WEIGHTS = {"yolo11n.pt": "coco8.yaml", "yolo11n-pose.pt": "coco8-pose.yaml"}
YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)


def fetch_yolo(name: str, calib: str, export: bool, int8: bool) -> None:
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
    variants = {f"{target.stem}_openvino_model": {"dynamic": True}}
    if int8:
        variants[f"{target.stem}_int8_openvino_model"] = {
            "dynamic": True,
            "int8": True,
            "data": calib,
        }
    for dirname, kwargs in variants.items():
        if (MODELS / dirname).exists():
            print(f"ok {MODELS / dirname}")
            continue
        out = YOLO(str(target)).export(format="openvino", imgsz=640, **kwargs)
        print(f"exported {out}")


def fetch_yunet() -> None:
    target = MODELS / Path(YUNET_URL).name
    if target.exists():
        print(f"ok {target}")
        return
    tmp = target.with_suffix(".part")
    urllib.request.urlretrieve(YUNET_URL, tmp)
    tmp.rename(target)
    print(f"downloaded {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-export", action="store_true", help="no OpenVINO export")
    parser.add_argument("--no-int8", action="store_true", help="skip INT8 (NNCF) export")
    args = parser.parse_args()
    MODELS.mkdir(exist_ok=True)
    for name, calib in YOLO_WEIGHTS.items():
        fetch_yolo(name, calib, export=not args.skip_export, int8=not args.no_int8)
    fetch_yunet()


if __name__ == "__main__":
    main()
