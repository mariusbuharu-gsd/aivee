"""Face blur before any snapshot leaves the device (OpenCV YuNet + Gaussian blur)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

PixelBox = tuple[int, int, int, int]  # x, y, w, h in pixels

DEFAULT_YUNET = Path("models/face_detection_yunet_2023mar.onnx")


class FaceBoxes(Protocol):
    def __call__(self, image: np.ndarray) -> list[PixelBox]: ...


class YuNetFaces:
    """`cv2.FaceDetectorYN` wrapper returning pixel face boxes."""

    def __init__(self, model_path: str | Path = DEFAULT_YUNET, score_threshold: float = 0.6):
        if not Path(model_path).exists():
            raise FileNotFoundError(f"{model_path} missing: run tools/download_models.py")
        self._det = cv2.FaceDetectorYN.create(
            str(model_path), "", (320, 320), score_threshold, 0.3, 5000
        )

    def __call__(self, image: np.ndarray) -> list[PixelBox]:
        h, w = image.shape[:2]
        self._det.setInputSize((w, h))
        _, faces = self._det.detect(image)
        if faces is None:
            return []
        return [(int(f[0]), int(f[1]), int(f[2]), int(f[3])) for f in faces]


def blur_boxes(image: np.ndarray, boxes: Sequence[PixelBox], pad: float = 0.25) -> np.ndarray:
    """Return a copy with each box (grown by `pad` on every side) heavily blurred."""
    out = image.copy()
    h, w = out.shape[:2]
    for x, y, bw, bh in boxes:
        px, py = int(bw * pad), int(bh * pad)
        x1, y1 = max(0, x - px), max(0, y - py)
        x2, y2 = min(w, x + bw + px), min(h, y + bh + py)
        if x2 <= x1 or y2 <= y1:
            continue
        roi = out[y1:y2, x1:x2]
        k = max(15, (max(x2 - x1, y2 - y1) // 2) | 1)  # odd kernel, scales with face size
        out[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (k, k), 0)
    return out


class FaceBlurrer:
    def __init__(self, faces: FaceBoxes | None = None) -> None:
        self._faces: FaceBoxes = faces if faces is not None else YuNetFaces()

    def blur(self, image: np.ndarray) -> np.ndarray:
        return blur_boxes(image, self._faces(image))


def encode_jpeg(image: np.ndarray, quality: int = 80) -> bytes:
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise ValueError("JPEG encoding failed")
    return bytes(buf.tobytes())
