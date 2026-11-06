"""tools/record_clip.py: record a source to an mp4 that FileSource replays."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import cv2
import numpy as np
from aivee_edge.adapters.capture import FileSource

TOOL = Path(__file__).resolve().parents[3] / "tools" / "record_clip.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("record_clip", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["record_clip"] = module
    spec.loader.exec_module(module)
    return module


record_clip = _load()


def _clip(path: Path, seconds: int = 3, fps: int = 20, size: tuple[int, int] = (64, 48)) -> Path:
    w, h = size
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"mp4v"), fps, (w, h))
    for i in range(seconds * fps):
        frame = np.full((h, w, 3), i % 255, np.uint8)
        writer.write(frame)
    writer.release()
    return path


def test_copies_needed_keeps_real_time_playback() -> None:
    # 10 fps output: a frame at 0.35 s must be the 4th frame; gaps are filled with repeats.
    assert record_clip.copies_needed(written=0, elapsed_s=0.0, fps=10) == 1
    assert record_clip.copies_needed(written=1, elapsed_s=0.35, fps=10) == 3
    assert record_clip.copies_needed(written=4, elapsed_s=0.36, fps=10) == 0


def test_records_n_seconds_rotated_and_replays_through_file_source(tmp_path: Path) -> None:
    source = _clip(tmp_path / "in.mp4", seconds=3)
    out = tmp_path / "recordings" / "demo.mp4"
    code = record_clip.main(
        [
            "--source",
            str(source),
            "--seconds",
            "2",
            "--fps",
            "10",
            "--rotate",
            "90",
            "--out",
            str(out),
        ]
    )
    assert code == 0 and out.is_file()

    replay = FileSource(out, target_fps=0)
    frames = []
    while (item := replay.read()) is not None:
        frames.append(item[1])
    replay.close()
    assert replay.native_fps == 10
    assert 19 <= len(frames) <= 21  # 2 s at 10 fps
    assert frames[0].shape[:2] == (64, 48)  # 64x48 turned upright → 48 wide, 64 high


def test_unreadable_source_fails_cleanly(tmp_path: Path) -> None:
    out = tmp_path / "x.mp4"
    assert (
        record_clip.main(
            ["--source", str(tmp_path / "nope.mp4"), "--seconds", "1", "--out", str(out)]
        )
        == 2
    )
    assert not out.exists()
