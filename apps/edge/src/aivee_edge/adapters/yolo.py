"""YOLO + ByteTrack detector: persons become tracks, table objects become ObjectObs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from aivee_edge.domain.observation import BBox, Frame, ObjectObs, TrackObs

PERSON = "person"
# COCO subset relevant to a restaurant table ("dining table" is excluded on purpose:
# tables are drawn as zones, detecting them only adds noise).
DEFAULT_CLASSES: tuple[str, ...] = (
    PERSON,
    "bottle",
    "wine glass",
    "cup",
    "fork",
    "knife",
    "spoon",
    "bowl",
)


def _clamp(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def normalise_box(xyxy: Sequence[float], width: int, height: int) -> BBox:
    x1, y1, x2, y2 = (float(v) for v in xyxy)
    return (_clamp(x1 / width), _clamp(y1 / height), _clamp(x2 / width), _clamp(y2 / height))


def map_results(
    boxes_xyxy: Sequence[Sequence[float]],
    cls_ids: Sequence[int],
    track_ids: Sequence[int | None] | None,
    confs: Sequence[float],
    names: Mapping[int, str],
    width: int,
    height: int,
    ts: float = 0.0,
) -> Frame:
    """Pure mapping from raw detector output (pixel boxes) to a domain Frame.

    Persons without a track id (tracker not yet confirmed) are skipped; objects do
    not need one. `track_ids=None` means the tracker returned no ids at all.
    """
    tracks: list[TrackObs] = []
    objects: list[ObjectObs] = []
    for i, (box, cls_id, conf) in enumerate(zip(boxes_xyxy, cls_ids, confs, strict=True)):
        label = names.get(int(cls_id), str(cls_id))
        bbox = normalise_box(box, width, height)
        if label == PERSON:
            tid = track_ids[i] if track_ids is not None else None
            if tid is None:
                continue
            tracks.append(TrackObs(track_id=int(tid), bbox=bbox, confidence=float(conf)))
        else:
            objects.append(ObjectObs(label=label, bbox=bbox, confidence=float(conf)))
    return Frame(ts=ts, tracks=tuple(tracks), objects=tuple(objects))


def class_ids_for(names: Mapping[int, str], wanted: Sequence[str]) -> list[int]:
    by_name = {v: k for k, v in names.items()}
    missing = [w for w in wanted if w not in by_name]
    if missing:
        raise ValueError(f"classes not in model: {missing}")
    return [by_name[w] for w in wanted]


class YoloDetector:
    """PersonDetector backed by ultralytics (`.pt` or an `*_openvino_model/` dir)."""

    def __init__(
        self,
        model_path: str | Path,
        conf: float = 0.35,
        classes: Sequence[str] = DEFAULT_CLASSES,
        imgsz: int = 640,
        tracker: str = "bytetrack.yaml",
    ) -> None:
        from ultralytics import YOLO

        self._model: Any = YOLO(str(model_path), task="detect")
        self._names: dict[int, str] = dict(self._model.names)
        self._class_ids = class_ids_for(self._names, classes)
        self._conf = conf
        self._imgsz = imgsz
        self._tracker = tracker
        self.last_result: Any = None

    def detect(self, image: Any, ts: float) -> Frame:
        results = self._model.track(
            image,
            persist=True,
            tracker=self._tracker,
            classes=self._class_ids,
            conf=self._conf,
            imgsz=self._imgsz,
            verbose=False,
        )
        result = results[0]
        self.last_result = result
        height, width = result.orig_shape
        boxes = result.boxes
        ids = boxes.id
        return map_results(
            boxes_xyxy=boxes.xyxy.tolist(),
            cls_ids=[int(c) for c in boxes.cls.tolist()],
            track_ids=None if ids is None else [int(i) for i in ids.tolist()],
            confs=boxes.conf.tolist(),
            names=self._names,
            width=int(width),
            height=int(height),
            ts=ts,
        )
