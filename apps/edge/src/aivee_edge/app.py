"""Wire real adapters into the EdgePipeline and run it until the source ends or a signal.

Vision adapters (OpenCV, ultralytics, open_clip) are imported lazily so this module, the
fake edge and the tests work without the heavy dependencies installed.
"""

import importlib
import logging
import signal
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FrameType, ModuleType
from typing import Any

from aivee_contracts.geometry import CameraConfig

from aivee_edge.adapters.clip_visual import BackgroundVisualScorer, InlineVisualScorer
from aivee_edge.adapters.mqtt import MqttEdgeClient
from aivee_edge.domain.observation import BBox
from aivee_edge.domain.ports import FrameSource, Image, PersonDetector, VisualScorer
from aivee_edge.domain.role import StaffWeights
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


def clip_clock(epoch: datetime) -> Callable[[float], datetime]:
    """Event time for an offline clip run: the clip position counted from `epoch`."""

    def to_datetime(ts: float) -> datetime:
        return epoch + timedelta(seconds=ts)

    return to_datetime


EXIT_NO_STATE = 4
"""Offline clip run: the retained config or rules did not arrive in time."""

OFFLINE_DETECTIONS_INTERVAL_S = 1e9
"""An offline clip run publishes no live boxes: nobody watches it, and at many times real
speed they would flood the broker."""


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


CROP_PAD = 0.1
"""Padding around a person crop, as a share of the box size on every side."""


class BlurredJpeg:
    """Pipeline `SnapshotMaker`: face blur, then JPEG (whole frame or one person)."""

    def __init__(self, blurrer: Any, encode: Any) -> None:
        self._blurrer = blurrer
        self._encode = encode

    def make(self, image: Image) -> bytes | None:
        try:
            return bytes(self._encode(self._blurrer.blur(image)))
        except Exception:
            log.exception("snapshot failed; publishing the alert without one")
            return None

    def crop(self, image: Image, bbox: BBox) -> bytes | None:
        h, w = image.shape[:2]  # type: ignore[attr-defined]
        x1, y1, x2, y2 = bbox
        px, py = (x2 - x1) * CROP_PAD, (y2 - y1) * CROP_PAD
        left, top = max(0, int((x1 - px) * w)), max(0, int((y1 - py) * h))
        right, bottom = min(w, int((x2 + px) * w)), min(h, int((y2 + py) * h))
        if right <= left or bottom <= top or x2 <= x1 or y2 <= y1:
            return None
        try:
            # Blur on the full frame: YuNet finds faces better with the context around them.
            blurred = self._blurrer.blur(image)
            return bytes(self._encode(blurred[top:bottom, left:right]))
        except Exception:
            log.exception("person crop failed; publishing the suggestion without one")
            return None


@dataclass
class Vision:
    source: FrameSource
    detector: PersonDetector
    pose: PoseEstimator | None
    embedder: Embedder | None
    snapshots: SnapshotMaker | None
    visual: VisualScorer | None = None


def build_vision(settings: EdgeSettings) -> Vision:
    try:
        capture = _adapter("capture")
        if settings.source.startswith("mqtt-frames://"):  # cloud mode over HTTPS
            source = _adapter("mqtt_frames").open_frames_source(
                settings.source,
                host=settings.mqtt_host,
                port=settings.mqtt_port,
                user=settings.mqtt_edge_user,
                password=settings.mqtt_edge_password,
                site=settings.site,
                device=settings.device,
                rotate=settings.rotate,
            )
        elif Path(settings.source).is_file():
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
        visual: VisualScorer | None = None
        if settings.visual_hz > 0:
            # Lazy: the CLIP weights load on first use, i.e. when a visual rule arrives, so
            # this import needs neither torch nor open_clip yet.
            offline = settings.clip_epoch is not None
            visual = InlineVisualScorer() if offline else BackgroundVisualScorer()
        snapshots = None
        if settings.blur:
            blur = _adapter("blur")
            faces = blur.YuNetFaces(settings.yunet_model)
            snapshots = BlurredJpeg(blur.FaceBlurrer(faces), blur.encode_jpeg)
    except VisionUnavailable:
        raise
    except (OSError, ValueError) as e:  # missing model files, bad source
        raise VisionUnavailable(f"could not load vision adapters: {e}") from e
    if settings.progress_file:
        from aivee_edge.progress import ProgressSource

        source = ProgressSource(
            source, settings.progress_file, duration_s=getattr(source, "duration_s", None)
        )
    return Vision(source, detector, pose, embedder, snapshots, visual)


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
        transport=settings.mqtt_transport,
        tls=settings.mqtt_tls,
        ws_path=settings.mqtt_ws_path,
    )


def pipeline_tuning(settings: EdgeSettings) -> dict[str, Any]:
    """Scoring knobs from the environment, passed to the EdgePipeline as keyword args."""
    return {
        "visual_hz": settings.visual_hz,
        "appearance_low": settings.appearance_low,
        "appearance_high": settings.appearance_high,
        "staff_weights": StaffWeights(
            appearance=settings.staff_w_appearance,
            standing=settings.staff_w_standing,
            behaviour=settings.staff_w_behaviour,
        ),
    }


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
    offline = settings.clip_epoch is not None
    if settings.config_wait_s > 0 and not client.wait_for_state(settings.config_wait_s):
        log.error(
            "no_state camera=%s: retained config or rules missing after %.0fs",
            settings.camera_id,
            settings.config_wait_s,
        )
        client.stop()
        return EXIT_NO_STATE
    extra: dict[str, Any] = (
        {"detections_interval_s": OFFLINE_DETECTIONS_INTERVAL_S} if offline else {}
    )
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
        visual=vision.visual,
        commands=client,
        grace_s=settings.grace_s,
        arrive_s=settings.arrive_s,
        metrics_interval_s=settings.metrics_interval_s,
        to_datetime=clip_clock(settings.clip_epoch) if settings.clip_epoch else wall_clock,
        **pipeline_tuning(settings),
        **extra,
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
