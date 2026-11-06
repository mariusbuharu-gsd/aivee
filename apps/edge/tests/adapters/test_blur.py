from pathlib import Path

import cv2
import numpy as np
import pytest
from aivee_edge.adapters.blur import DEFAULT_YUNET, FaceBlurrer, PixelBox, encode_jpeg


def noisy_image() -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.integers(0, 256, size=(240, 320, 3), dtype=np.uint8)


def test_output_differs_inside_face_box_only() -> None:
    image = noisy_image()
    face: PixelBox = (100, 60, 40, 40)
    out = FaceBlurrer(faces=lambda _img: [face]).blur(image)

    assert out.shape == image.shape
    inside = (slice(60, 100), slice(100, 140))
    assert np.abs(out[inside].astype(int) - image[inside].astype(int)).mean() > 20
    assert out[inside].std() < image[inside].std() / 2  # smoothed
    # far from the (padded) box nothing changes
    assert np.array_equal(out[:40, :], image[:40, :])
    assert np.array_equal(out[:, 200:], image[:, 200:])
    # input is not modified in place
    assert not np.array_equal(out, image)


def test_no_faces_returns_identical_copy() -> None:
    image = noisy_image()
    out = FaceBlurrer(faces=lambda _img: []).blur(image)
    assert np.array_equal(out, image) and out is not image


def test_box_at_image_edge_is_clipped() -> None:
    image = noisy_image()
    out = FaceBlurrer(faces=lambda _img: [(300, 220, 50, 50), (-20, -20, 10, 10)]).blur(image)
    assert out.shape == image.shape


def test_encode_jpeg_roundtrip() -> None:
    data = encode_jpeg(noisy_image(), quality=70)
    assert data[:2] == b"\xff\xd8"
    decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (240, 320, 3)


YUNET = Path(__file__).parents[4] / DEFAULT_YUNET


@pytest.mark.integration
@pytest.mark.skipif(not YUNET.exists(), reason="run tools/download_models.py first")
def test_yunet_loads_and_finds_nothing_on_noise() -> None:
    from aivee_edge.adapters.blur import YuNetFaces

    assert YuNetFaces(YUNET)(np.zeros((240, 320, 3), dtype=np.uint8)) == []
