import itertools
from pathlib import Path

import cv2
import numpy as np
import pytest
from aivee_edge.adapters.capture import Cv2Source, FileSource, rotate


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    """30 frames at 30 fps (1 s); frame i has brightness 8*i so frames are tellable apart."""
    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 48))
    assert writer.isOpened()
    for i in range(30):
        writer.write(np.full((48, 64, 3), 8 * i, dtype=np.uint8))
    writer.release()
    return path


def drain(source: FileSource, limit: int = 1000) -> list[tuple[float, np.ndarray]]:
    out = []
    while len(out) < limit and (item := source.read()) is not None:
        out.append(item)
    return out


def test_file_source_yields_frames(clip: Path) -> None:
    frames = drain(FileSource(clip, target_fps=30))
    assert len(frames) == 30
    ts, image = frames[0]
    assert ts == 0.0
    assert image.shape == (48, 64, 3)


def test_file_source_drops_to_target_fps_with_video_timestamps(clip: Path) -> None:
    frames = drain(FileSource(clip, target_fps=10))
    assert len(frames) == 10
    stamps = [ts for ts, _ in frames]
    assert stamps == pytest.approx([i / 10 for i in range(10)], abs=1e-6)
    # every 3rd frame kept: brightness 0, 24, 48, ...
    assert [round(img.mean() / 24) for _, img in frames[:4]] == [0, 1, 2, 3]


def test_file_source_loop_keeps_timestamps_monotonic(clip: Path) -> None:
    frames = drain(FileSource(clip, target_fps=10, loop=True), limit=25)
    stamps = [ts for ts, _ in frames]
    assert len(stamps) == 25
    assert all(b > a for a, b in itertools.pairwise(stamps))
    assert stamps[10] == pytest.approx(1.0)


def test_file_source_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        FileSource(tmp_path / "nope.avi")


def test_cv2_source_drops_frames_by_wall_clock(clip: Path) -> None:
    now = [0.0]

    def clock() -> float:
        now[0] += 0.04  # each read advances 40 ms (25 fps camera)
        return now[0]

    source = Cv2Source(str(clip), target_fps=5, clock=clock, max_reconnects=0)
    first = source.read()
    second = source.read()
    assert first is not None and second is not None
    assert second[0] - first[0] >= 0.2 - 1e-9


def _marked() -> np.ndarray:
    """2x3 image whose top-left pixel is white, so every rotation is tellable apart."""
    image = np.zeros((2, 3, 3), dtype=np.uint8)
    image[0, 0] = 255
    return image


@pytest.mark.parametrize(
    ("degrees", "shape", "white"),
    [
        (0, (2, 3, 3), (0, 0)),
        (90, (3, 2, 3), (0, 1)),
        (180, (2, 3, 3), (1, 2)),
        (270, (3, 2, 3), (2, 0)),
    ],
)
def test_rotate_turns_the_image_clockwise(
    degrees: int, shape: tuple[int, ...], white: tuple[int, int]
) -> None:
    out = rotate(_marked(), degrees)
    assert out.shape == shape
    assert tuple(int(v) for v in np.argwhere(out[:, :, 0] == 255)[0]) == white


def test_rotate_rejects_other_angles() -> None:
    with pytest.raises(ValueError):
        rotate(_marked(), 45)


def test_file_source_applies_rotation_before_returning_frames(clip: Path) -> None:
    [(_, image)] = drain(FileSource(clip, target_fps=30, rotate=90), limit=1)
    assert image.shape == (64, 48, 3)


def test_cv2_source_applies_rotation(clip: Path) -> None:
    source = Cv2Source(str(clip), target_fps=0, max_reconnects=0, rotate=270)
    item = source.read()
    assert item is not None and item[1].shape == (64, 48, 3)
    source.close()


def test_cv2_source_gives_up_after_max_reconnects(tmp_path: Path) -> None:
    sleeps: list[float] = []
    source = Cv2Source(
        str(tmp_path / "missing.avi"), target_fps=5, max_reconnects=3, sleep=sleeps.append
    )
    assert source.read() is None
    assert sleeps == [0.5, 1.0, 2.0]
