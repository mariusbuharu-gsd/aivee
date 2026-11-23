"""YOLO + ByteTrack detector: persons become tracks, table objects become ObjectObs.

The detector keeps only `DEFAULT_CLASSES` (the restaurant table subset) unless rules ask
for more: `set_extra_classes` adds the COCO classes of `object_present` rules ("bear",
"dog"…) at run time. Names the model does not know are logged and skipped.

Tracker. ByteTrack matches confident boxes first, then uses low-score boxes (a person
half hidden behind a waiter) to keep existing tracks alive. So the model runs at
`TRACK_LOW_CONF` and the tracker config, generated per detector, carries the thresholds:
a new track still needs `PERSON_CONF`, and objects below it are dropped as before.
ByteTrack's `track_buffer` counts frames, so it is derived from the expected fps to keep
a lost track for `lost_track_s` seconds whatever the frame rate.
"""

from __future__ import annotations

import atexit
import logging
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from aivee_edge.domain.observation import BBox, Frame, ObjectObs, TrackObs

log = logging.getLogger("aivee_edge.yolo")

PERSON = "person"
# COCO subset relevant to a restaurant table ("dining table" is excluded on purpose:
# tables are drawn as zones, detecting them only adds noise). "knife" is excluded too:
# every table has one, so detecting it by default only feeds false alerts; an
# `object_present` rule that really asks for it still adds it via `set_extra_classes`.
DEFAULT_CLASSES: tuple[str, ...] = (
    PERSON,
    "bottle",
    "wine glass",
    "cup",
    "fork",
    "spoon",
    "bowl",
)


PERSON_CONF = 0.35
"""Confidence a box needs to start a track (person) or to count at all (object)."""
TRACK_LOW_CONF = 0.1
"""Lowest score fed to ByteTrack, for its second (low-score) association."""
LOST_TRACK_S = 4.0
"""How long a track that lost its box is kept for re-association."""
TRACK_MATCH_THRESH = 0.8


def track_buffer_frames(fps: float, seconds: float) -> int:
    """ByteTrack's `track_buffer` (frames) that keeps a lost track for `seconds` at `fps`."""
    if fps <= 0:
        raise ValueError("fps must be positive")
    return max(1, math.ceil(fps * seconds - 1e-9))


def tracker_config(
    fps: float,
    lost_track_s: float = LOST_TRACK_S,
    person_conf: float = PERSON_CONF,
    low_conf: float = TRACK_LOW_CONF,
) -> dict[str, Any]:
    """An ultralytics ByteTrack config (the keys of its `bytetrack.yaml`)."""
    if not 0 <= low_conf < person_conf <= 1:
        raise ValueError("need 0 <= low_conf < person_conf <= 1")
    return {
        "tracker_type": "bytetrack",
        "track_high_thresh": person_conf,
        "track_low_thresh": low_conf,
        "new_track_thresh": person_conf,
        "track_buffer": track_buffer_frames(fps, lost_track_s),
        "match_thresh": TRACK_MATCH_THRESH,
        "fuse_score": True,
    }


def write_tracker_yaml(cfg: Mapping[str, Any], directory: str | Path | None = None) -> Path:
    """Write `cfg` as a tracker YAML file (flat scalars only) and return its path."""
    fd, name = tempfile.mkstemp(prefix="aivee-bytetrack-", suffix=".yaml", dir=directory)
    lines = [f"{k}: {str(v).lower() if isinstance(v, bool) else v}" for k, v in cfg.items()]
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    return Path(name)


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
    min_object_conf: float = 0.0,
) -> Frame:
    """Pure mapping from raw detector output (pixel boxes) to a domain Frame.

    Persons without a track id (tracker not yet confirmed) are skipped; objects do
    not need one. `track_ids=None` means the tracker returned no ids at all. Objects
    below `min_object_conf` are dropped; a tracked person is kept at any score (the
    tracker only lets a low score extend a track that started confident).
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
        elif conf >= min_object_conf:
            objects.append(ObjectObs(label=label, bbox=bbox, confidence=float(conf)))
    aspect = width / height if height else None
    return Frame(ts=ts, tracks=tuple(tracks), objects=tuple(objects), aspect=aspect)


def class_ids_for(names: Mapping[int, str], wanted: Sequence[str]) -> list[int]:
    by_name = {v: k for k, v in names.items()}
    missing = [w for w in wanted if w not in by_name]
    if missing:
        raise ValueError(f"classes not in model: {missing}")
    return [by_name[w] for w in wanted]


def with_extra(
    names: Mapping[int, str], base: Sequence[str], extra: Sequence[str]
) -> tuple[list[int], list[str]]:
    """Class ids for `base` plus the known names of `extra`, and the unknown extra names."""
    by_name = {v: k for k, v in names.items()}
    ids = class_ids_for(names, base)
    unknown = []
    for name in extra:
        if name not in by_name:
            unknown.append(name)
        elif by_name[name] not in ids:
            ids.append(by_name[name])
    return ids, unknown


class YoloDetector:
    """PersonDetector backed by ultralytics (`.pt` or an `*_openvino_model/` dir)."""

    def __init__(
        self,
        model_path: str | Path,
        conf: float = PERSON_CONF,
        classes: Sequence[str] = DEFAULT_CLASSES,
        imgsz: int = 640,
        tracker: str | None = None,
        *,
        fps: float = 10.0,
        lost_track_s: float = LOST_TRACK_S,
        low_conf: float = TRACK_LOW_CONF,
    ) -> None:
        """`fps`: the rate frames will really arrive at (TARGET_FPS), for the tracker
        buffer. `tracker`: an ultralytics tracker YAML to use as is instead of the
        generated ByteTrack config (then `conf` is applied before it, as ultralytics does)."""
        from ultralytics import YOLO

        self._model: Any = YOLO(str(model_path), task="detect")
        self._names: dict[int, str] = dict(self._model.names)
        self._base = list(classes)
        self._class_ids = class_ids_for(self._names, classes)
        self._extra: list[str] = []
        self._conf = conf
        self._imgsz = imgsz
        if tracker is None:
            cfg = tracker_config(fps, lost_track_s, person_conf=conf, low_conf=low_conf)
            path = write_tracker_yaml(cfg)
            atexit.register(path.unlink, missing_ok=True)
            self._tracker = str(path)
            self._detect_conf = low_conf
            log.info(
                "tracker bytetrack fps=%.1f track_buffer=%d high=%.2f low=%.2f",
                fps,
                cfg["track_buffer"],
                conf,
                low_conf,
            )
        else:
            self._tracker = tracker
            self._detect_conf = conf
        self.last_result: Any = None

    def set_extra_classes(self, extra: Sequence[str]) -> None:
        """Also detect these COCO classes (from the rules), on top of the default subset."""
        wanted = sorted(set(extra))
        if wanted == self._extra:
            return
        self._extra = wanted
        self._class_ids, unknown = with_extra(self._names, self._base, wanted)
        if unknown:
            log.warning("detector_unknown_classes names=%s", ",".join(unknown))
        log.info("detector_classes extra=%s", ",".join(wanted) or "-")

    def detect(self, image: Any, ts: float) -> Frame:
        results = self._model.track(
            image,
            persist=True,
            tracker=self._tracker,
            classes=self._class_ids,
            conf=self._detect_conf,
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
            min_object_conf=self._conf,
        )
