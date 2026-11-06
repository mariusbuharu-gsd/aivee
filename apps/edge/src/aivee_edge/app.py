"""Wire real adapters into the EdgePipeline and run it until the source ends or a signal.

Vision adapters (OpenCV, ultralytics, open_clip) are imported lazily so this module, the
fake edge and the tests work without the heavy dependencies installed.
"""

import importlib
import logging
import signal
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType, ModuleType
from typing import Any

from aivee_contracts.geometry import CameraConfig

from aivee_edge.adapters.mqtt import MqttEdgeClient
from aivee_edge.domain.observation import BBox
from aivee_edge.domain.ports import FrameSource, Image, PersonDetector
from aivee_edge.pipeline import EdgePipeline, Embedder, PoseEstimator, SnapshotMaker
from aivee_edge.settings import EdgeSettings

log = logging.getLogger("aivee_edge")


class VisionUnavailable(RuntimeError):
    """A vision adapter or its dependencies could not be imported or loaded."""


def configure_logging(level: int = logging.INFO) -> None:
    """key=value messages on one line, easy to grep for `event_id=`."""
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def wall_clock(_ts: float) -> datetime:
    """Event time for live runs: source timestamps are monotonic or video time."""
    return datetime.now(UTC)


def _adapter(name: str) -> ModuleType:
    try:
        return importlib.import_module(f"aivee_edge.adapters.{name}")
    except ImportError as e:
        raise VisionUnavailable(
            f"vision adapter aivee_edge.adapters.{name} is not available ({e}). "
            "Install the vision dependencies or use tools/fake_edge.py for a demo without a camera."
        ) from e


# -- glue between the vision adapters and the pipeline ports --------------------------


class CropEmbedder:
    """Pipeline `Embedder`: crops the normalised bbox from a BGR array and embeds it."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def embed(self, image: Image, bbox: BBox) -> list[float] | None:
        h, w = image.shape[:2]  # type: ignore[attr-defined]
        x1, y1, x2, y2 = bbox
        crop = image[int(y1 * h) : int(y2 * h), int(x1 * w) : int(x2 * w)]  # type: ignore[index]
        if crop.size == 0:
            return None
        return list(self._inner.embed(crop))


class BlurredJpeg:
    """Pipeline `SnapshotMaker`: face blur, then JPEG."""

    def __init__(self, blurrer: Any, encode: Any) -> None:
        self._blurrer = blurrer
        self._encode = encode

    def make(self, image: Image) -> bytes | None:
        try:
            return bytes(self._encode(self._blurrer.blur(image)))
        except Exception:
            log.exception("snapshot failed; publishing the alert without one")
            return None


@dataclass
class Vision:
    source: FrameSource
    detector: PersonDetector
    pose: PoseEstimator | None
    embedder: Embedder | None
    snapshots: SnapshotMaker | None


def build_vision(settings: EdgeSettings) -> Vision:
    try:
        capture = _adapter("capture")
        if Path(settings.source).is_file():
            source = capture.FileSource(
                settings.source, settings.target_fps, settings.loop_file, rotate=settings.rotate
            )
        else:
            source = capture.Cv2Source(settings.source, settings.target_fps, rotate=settings.rotate)
        detector = _adapter("yolo").YoloDetector(settings.detector_model)
        pose = _adapter("pose").PoseEstimator(settings.pose_model) if settings.pose_model else None
        embedder = (
            CropEmbedder(_adapter("clip_embedder").ClipEmbedder()) if settings.appearance else None
        )
        snapshots = None
        if settings.blur:
            blur = _adapter("blur")
            faces = blur.YuNetFaces(settings.yunet_model)
            snapshots = BlurredJpeg(blur.FaceBlurrer(faces), blur.encode_jpeg)
    except VisionUnavailable:
        raise
    except (OSError, ValueError) as e:  # missing model files, bad source
        raise VisionUnavailable(f"could not load vision adapters: {e}") from e
    return Vision(source, detector, pose, embedder, snapshots)


def build_client(settings: EdgeSettings) -> MqttEdgeClient:
    fallback = CameraConfig(id=settings.camera_id, name=settings.camera_id, source=settings.source)
    return MqttEdgeClient(
        settings.mqtt_host,
        settings.mqtt_port,
        settings.mqtt_edge_user,
        settings.mqtt_edge_password,
        settings.site,
        settings.device,
        camera=fallback,
        camera_id=settings.camera_id,
    )


def install_stop_signals(stop: threading.Event) -> None:
    def handler(signum: int, _frame: FrameType | None) -> None:
        log.info("signal=%s stopping", signal.Signals(signum).name)
        stop.set()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def run(settings: EdgeSettings, stop: threading.Event | None = None) -> int:
    """Run the live edge; returns the process exit code."""
    try:
        vision = build_vision(settings)
    except VisionUnavailable as e:
        log.error("%s", e)
        return 2
    client = build_client(settings)
    stop = stop or threading.Event()
    install_stop_signals(stop)
    try:
        client.start()
    except TimeoutError as e:
        log.error("mqtt_unavailable host=%s port=%d: %s", settings.mqtt_host, settings.mqtt_port, e)
        return 3
    pipeline = EdgePipeline(
        vision.source,
        vision.detector,
        client,
        client,
        device=settings.device,
        camera_id=settings.camera_id,
        pose=vision.pose,
        embedder=vision.embedder,
        profiles=client.profiles,
        snapshots=vision.snapshots,
        commands=client,
        grace_s=settings.grace_s,
        metrics_interval_s=settings.metrics_interval_s,
        to_datetime=wall_clock,
    )
    log.info(
        "edge started site=%s device=%s camera=%s source=%s",
        settings.site,
        settings.device,
        settings.camera_id,
        settings.source,
    )
    try:
        frames = pipeline.run(stop)
        log.info("edge stopped frames=%d", frames)
    finally:
        client.stop()
        close = getattr(vision.source, "close", None)
        if callable(close):
            close()
    return 0
