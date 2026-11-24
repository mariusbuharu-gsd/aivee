"""tools/download_models.py: which data calibrates the INT8 exports."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import cv2
import numpy as np
import pytest
import yaml  # type: ignore[import-untyped]

TOOL = Path(__file__).resolve().parents[3] / "tools" / "download_models.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("download_models", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["download_models"] = module
    spec.loader.exec_module(module)
    return module


dm = _load()
NAMES = {0: "person", 1: "bicycle"}


def test_defaults_calibrate_on_more_than_eight_images() -> None:
    args = dm.parse_args([])
    assert dm.calibration_for("yolo11n.pt", args) == "coco128.yaml"
    assert dm.calibration_for("yolo11n-pose.pt", args) == "coco8-pose.yaml"


def test_calibration_datasets_are_configurable() -> None:
    args = dm.parse_args(["--calib-data", "my.yaml", "--calib-pose-data", "my-pose.yaml"])
    assert dm.calibration_for("yolo11n.pt", args) == "my.yaml"
    assert dm.calibration_for("yolo11n-pose.pt", args) == "my-pose.yaml"


def test_venue_frames_become_an_unlabelled_dataset(tmp_path: Path) -> None:
    frames = tmp_path / "frames"
    frames.mkdir()
    cv2.imwrite(str(frames / "a.jpg"), np.zeros((48, 64, 3), np.uint8))
    det = yaml.safe_load(dm.frames_dataset(frames, NAMES, pose=False, out=tmp_path).read_text())
    assert det["path"] == str(frames.resolve())
    assert det["val"] == det["train"] == "."
    assert det["names"] == NAMES and "kpt_shape" not in det
    pose = yaml.safe_load(dm.frames_dataset(frames, NAMES, pose=True, out=tmp_path).read_text())
    assert pose["kpt_shape"] == [17, 3] and len(pose["flip_idx"]) == 17


def test_frames_dataset_needs_images(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no images"):
        dm.frames_dataset(tmp_path, NAMES, pose=False, out=tmp_path)


def test_clips_are_sampled_into_calibration_frames(tmp_path: Path) -> None:
    clip = tmp_path / "sala.mp4"
    writer = cv2.VideoWriter(str(clip), cv2.VideoWriter.fourcc(*"mp4v"), 10.0, (64, 48))
    for i in range(50):  # 5 s at 10 fps
        writer.write(np.full((48, 64, 3), i * 4, np.uint8))
    writer.release()
    out = tmp_path / "frames"
    written = dm.sample_clips([clip], out, every_s=1.0)
    assert written == 5 and len(list(out.glob("*.jpg"))) == 5


def test_force_is_needed_to_replace_an_existing_int8_export() -> None:
    assert dm.parse_args([]).force is False
    assert dm.parse_args(["--force-int8"]).force is True
