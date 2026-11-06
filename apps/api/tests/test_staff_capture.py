"""Guided staff capture from a live camera, without models or a database."""

import math
from typing import Any

import pytest
from aivee_api.frames.store import LiveFrames
from aivee_api.staff.capture import (
    CaptureStore,
    capture_candidates,
    sample_frames,
)
from aivee_api.staff.enrol import Enroller, Upload, largest_box


def test_largest_box_picks_the_biggest_area() -> None:
    small, big = (0.0, 0.0, 10.0, 10.0), (5.0, 5.0, 40.0, 60.0)
    assert largest_box([small, big, small]) == big
    assert largest_box([]) is None


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_sampling_keeps_one_frame_per_tick_and_skips_repeats() -> None:
    clock = _Clock()
    frames = LiveFrames(clock=clock)
    frames.put("cam1", b"\xff\xd8\xff1")
    posted = iter([b"\xff\xd8\xff2", None, b"\xff\xd8\xff3", None])

    async def sleep(seconds: float) -> None:
        clock.now += seconds
        jpeg = next(posted, None)
        if jpeg is not None:
            frames.put("cam1", jpeg)

    got = await sample_frames(frames, "cam1", seconds=6, interval_s=1.5, sleep=sleep)
    assert got == [b"\xff\xd8\xff1", b"\xff\xd8\xff2", b"\xff\xd8\xff3"]


async def test_sampling_a_silent_camera_gives_nothing() -> None:
    async def sleep(seconds: float) -> None:
        return None

    assert await sample_frames(LiveFrames(), "cam1", 6, 1.5, sleep) == []


class _Decoder:
    def frames(self, upload: Upload) -> list[Any]:
        return [upload.data[-1]]


class _Crowd:
    """Frame n has people of heights n, 2n and 3n; the largest-only mode keeps 3n."""

    def __init__(self) -> None:
        self.modes: list[bool] = []

    def crops(self, frame: Any, largest_only: bool = False) -> list[Any]:
        self.modes.append(largest_only)
        if frame == 0:
            return []
        people = [frame, frame * 2, frame * 3]
        return [max(people)] if largest_only else people


class _Embed:
    def embed(self, crop: Any) -> list[float]:
        return [float(crop), 0.0]


class _Thumb:
    def jpeg(self, crop: Any, max_side: int) -> bytes:
        return f"t{crop}".encode()


def test_candidates_keep_only_the_largest_person_per_frame() -> None:
    crowd = _Crowd()
    enroller = Enroller(_Decoder(), crowd, _Embed(), _Thumb())
    crops, thumbs = capture_candidates(enroller, [bytes([1]), bytes([0]), bytes([2])])
    assert crops == [3, 6]
    assert thumbs == [b"t3", b"t6"]
    assert set(crowd.modes) == {True}


def test_photo_upload_keeps_every_person_by_default() -> None:
    enroller = Enroller(_Decoder(), _Crowd(), _Embed(), _Thumb())
    result = enroller.enrol([Upload("a.jpg", "image/jpeg", bytes([1]))])
    assert len(result.embeddings) == 3


def test_embed_crops_normalises() -> None:
    enroller = Enroller(_Decoder(), _Crowd(), _Embed(), _Thumb())
    [vec] = enroller.embed_crops([3])
    assert math.isclose(vec[0], 1.0)


def test_thumbnail_without_an_encoder_is_a_model_error() -> None:
    with pytest.raises(RuntimeError):
        Enroller(_Decoder(), _Crowd(), _Embed()).thumbnail(1)


def test_store_hands_a_capture_back_only_to_its_owner_until_it_expires() -> None:
    clock = _Clock()
    store = CaptureStore(ttl_s=600, clock=clock)
    token = store.put("u1", "cam1", "loc", [1, 2])
    assert store.get(token, "u2") is None
    got = store.get(token, "u1")
    assert got is not None and got.crops == [1, 2] and got.location_id == "loc"
    store.drop(token)
    assert store.get(token, "u1") is None

    token = store.put("u1", "cam1", "loc", [1])
    clock.now += 601
    assert store.get(token, "u1") is None


def test_store_keeps_a_bounded_number_of_captures() -> None:
    store = CaptureStore(max_items=2)
    first = store.put("u", "c", "l", [1])
    store.put("u", "c", "l", [2])
    store.put("u", "c", "l", [3])
    assert store.get(first, "u") is None
    assert len(store) == 2
