"""Heavy enrolment adapters (OpenCV, ultralytics YOLO, the edge's CLIP embedder). Imported
lazily: they come with the `ml` extra (aivee-edge), installed by `uv sync --all-packages`."""

import logging
import os
import tempfile
import threading
from typing import Any

from aivee_api.staff.enrol import (
    FRAME_INTERVAL_S,
    MAX_VIDEO_FRAMES,
    Enroller,
    PersonCropper,
    Upload,
    largest_box,
)

log = logging.getLogger(__name__)

PERSON_CLASS = 0
MIN_CROP_PX = 32


class Cv2FrameDecoder:
    def frames(self, upload: Upload) -> list[Any]:
        import cv2
        import numpy as np

        if not upload.is_video:
            image = cv2.imdecode(np.frombuffer(upload.data, np.uint8), cv2.IMREAD_COLOR)
            return [] if image is None else [image]
        suffix = os.path.splitext(upload.filename)[1] or ".mp4"
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(upload.data)
            tmp.flush()
            capture = cv2.VideoCapture(tmp.name)
            try:
                fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
                step = max(1, round(fps * FRAME_INTERVAL_S))
                frames: list[Any] = []
                index = 0
                while len(frames) < MAX_VIDEO_FRAMES:
                    ok, frame = capture.read()
                    if not ok:
                        break
                    if index % step == 0:
                        frames.append(frame)
                    index += 1
                return frames
            finally:
                capture.release()


class WholeImageCropper:
    """Fallback when no detector is available: the owner uploaded a photo of one person."""

    def crops(self, frame: Any, largest_only: bool = False) -> list[Any]:
        return [frame]


class YoloPersonCropper:
    def __init__(self, weights: str, conf: float = 0.4) -> None:
        self._weights = weights
        self._conf = conf
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                from ultralytics import YOLO  # type: ignore[attr-defined]

                self._model = YOLO(self._weights)
        return self._model

    def crops(self, frame: Any, largest_only: bool = False) -> list[Any]:
        result = self._load()(frame, classes=[PERSON_CLASS], conf=self._conf, verbose=False)[0]
        h, w = frame.shape[:2]
        boxes = [tuple(b) for b in result.boxes.xyxy.tolist()]
        if largest_only:
            biggest = largest_box(boxes)
            boxes = [] if biggest is None else [biggest]
        out = []
        for x1, y1, x2, y2 in boxes:
            x1, y1 = max(0, int(x1)), max(0, int(y1))
            x2, y2 = min(w, int(x2)), min(h, int(y2))
            if x2 - x1 >= MIN_CROP_PX and y2 - y1 >= MIN_CROP_PX:
                out.append(frame[y1:y2, x1:x2])
        return out


class Cv2CropEncoder:
    def jpeg(self, crop: Any, max_side: int) -> bytes:
        import cv2

        h, w = crop.shape[:2]
        scale = min(1.0, max_side / max(h, w, 1))
        if scale < 1.0:
            crop = cv2.resize(crop, (max(1, int(w * scale)), max(1, int(h * scale))))
        ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            raise RuntimeError("could not encode the thumbnail")
        return bytes(buf)


class LazyEdgeClipEmbedder:
    """The edge's own ClipEmbedder (same model, weights and preprocessing, so centroids are
    comparable with what the edge computes), loaded on first use to keep startup fast."""

    def __init__(self) -> None:
        self._inner: Any = None
        self._lock = threading.Lock()

    def embed(self, crop: Any) -> list[float]:
        with self._lock:
            if self._inner is None:
                from aivee_edge.adapters.clip_embedder import ClipEmbedder

                self._inner = ClipEmbedder()
        vec: list[float] = self._inner.embed(crop)
        return vec


def build_enroller(yolo_weights: str) -> Enroller | None:
    """The real enroller, or None when the `ml` extra is not installed."""
    try:
        import aivee_edge.adapters.clip_embedder  # noqa: F401
        import cv2  # noqa: F401
        import open_clip  # type: ignore[import-untyped]  # noqa: F401
    except ImportError:
        log.warning("enrolment disabled: install the api 'ml' extra (aivee-edge models)")
        return None
    cropper: PersonCropper
    try:
        import ultralytics  # noqa: F401

        cropper = YoloPersonCropper(yolo_weights)
    except ImportError:
        log.warning("ultralytics not installed: enrolment uses whole images as crops")
        cropper = WholeImageCropper()
    return Enroller(Cv2FrameDecoder(), cropper, LazyEdgeClipEmbedder(), Cv2CropEncoder())
