"""YOLO pose: COCO-17 keypoints per tracked person, matched to tracks by IoU."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from aivee_edge.domain.observation import BBox, TrackObs

Keypoint = tuple[float, float, float]  # (x, y, conf), normalised, y grows downward
Keypoints = tuple[Keypoint, ...]  # COCO-17 order


def iou(a: BBox, b: BBox) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0.0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)


def match_by_iou(
    tracks: Mapping[int, BBox], detections: Sequence[BBox], min_iou: float = 0.3
) -> dict[int, int]:
    """Greedy one-to-one matching: track id -> detection index, best IoU first."""
    pairs = sorted(
        (
            (score, tid, di)
            for tid, tb in tracks.items()
            for di, db in enumerate(detections)
            if (score := iou(tb, db)) >= min_iou
        ),
        reverse=True,
    )
    matched: dict[int, int] = {}
    used: set[int] = set()
    for _, tid, di in pairs:
        if tid in matched or di in used:
            continue
        matched[tid] = di
        used.add(di)
    return matched


def normalise_keypoints(
    xy: Sequence[Sequence[float]], conf: Sequence[float] | None, width: int, height: int
) -> Keypoints:
    confs = conf if conf is not None else [1.0] * len(xy)
    return tuple(
        (float(x) / width, float(y) / height, float(c)) for (x, y), c in zip(xy, confs, strict=True)
    )


class PoseEstimator:
    """Runs YOLO pose on the full frame and assigns keypoints to the given tracks."""

    def __init__(
        self, model_path: str | Path, conf: float = 0.3, imgsz: int = 640, min_iou: float = 0.3
    ) -> None:
        from ultralytics import YOLO

        self._model: Any = YOLO(str(model_path), task="pose")
        self._conf = conf
        self._imgsz = imgsz
        self._min_iou = min_iou

    def estimate(self, image: Any, tracks: Sequence[TrackObs]) -> dict[int, Keypoints]:
        if not tracks:
            return {}
        result = self._model.predict(
            image, conf=self._conf, imgsz=self._imgsz, classes=[0], verbose=False
        )[0]
        if result.keypoints is None or len(result.boxes) == 0:
            return {}
        height, width = result.orig_shape
        boxes: list[BBox] = [
            (x1 / width, y1 / height, x2 / width, y2 / height)
            for x1, y1, x2, y2 in result.boxes.xyxy.tolist()
        ]
        kxy = result.keypoints.xy.tolist()
        kconf = None if result.keypoints.conf is None else result.keypoints.conf.tolist()
        matches = match_by_iou({t.track_id: t.bbox for t in tracks}, boxes, self._min_iou)
        return {
            tid: normalise_keypoints(kxy[di], None if kconf is None else kconf[di], width, height)
            for tid, di in matches.items()
        }
