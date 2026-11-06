"""Enrolment: uploaded photos or a short video → person crops → appearance embeddings.

Pure orchestration over three ports; the heavy adapters live in `staff/adapters.py`.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

FRAME_INTERVAL_S = 0.5
MAX_VIDEO_FRAMES = 60


@dataclass(frozen=True)
class Upload:
    filename: str
    content_type: str
    data: bytes

    @property
    def is_video(self) -> bool:
        return self.content_type.startswith("video/")


class FrameDecoder(Protocol):
    """Images → one frame; videos → one frame every FRAME_INTERVAL_S. Frames are BGR arrays."""

    def frames(self, upload: Upload) -> list[Any]: ...


class PersonCropper(Protocol):
    def crops(self, frame: Any, largest_only: bool = False) -> list[Any]:
        """Person crops of a frame; with `largest_only`, at most the biggest one (the person
        standing in front of the camera, not the guests behind them)."""
        ...


class CropEncoder(Protocol):
    def jpeg(self, crop: Any, max_side: int) -> bytes:
        """A small JPEG of a crop, its longer side at most `max_side` px."""
        ...


Box = tuple[float, float, float, float]


def largest_box(boxes: Sequence[Box]) -> Box | None:
    """The box (x1, y1, x2, y2) with the biggest area, or None."""
    return max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), default=None)


class ImageEmbedder(Protocol):
    def embed(self, crop: Any) -> list[float]: ...


def l2_normalise(vec: Iterable[float]) -> list[float]:
    values = [float(v) for v in vec]
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values] if norm > 0 else values


@dataclass
class EnrolResult:
    frames: int = 0
    crops: int = 0
    embeddings: list[list[float]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # filenames that gave no person


class Enroller:
    def __init__(
        self,
        decoder: FrameDecoder,
        cropper: PersonCropper,
        embedder: ImageEmbedder,
        encoder: CropEncoder | None = None,
    ) -> None:
        self._decoder = decoder
        self._cropper = cropper
        self._embedder = embedder
        self._encoder = encoder

    def enrol(self, uploads: Sequence[Upload]) -> EnrolResult:
        """CPU-bound: call it from a worker thread."""
        result = EnrolResult()
        for upload in uploads:
            found = 0
            for frame in self._decoder.frames(upload):
                result.frames += 1
                crops = self._cropper.crops(frame)
                if not crops and not upload.is_video:
                    # A photo with no detectable person is usually the uniform itself
                    # (e.g. a T-shirt on a hanger): embed the whole image.
                    crops = [frame]
                for crop in crops:
                    result.embeddings.append(l2_normalise(self._embedder.embed(crop)))
                    found += 1
            result.crops += found
            if found == 0:
                result.skipped.append(upload.filename)
        return result

    def largest_person(self, jpeg: bytes) -> Any | None:
        """The biggest person in a live camera frame, or None. CPU-bound. No whole-image
        fallback here: a frame without anyone is just skipped."""
        for frame in self._decoder.frames(Upload("frame.jpg", "image/jpeg", jpeg)):
            crops = self._cropper.crops(frame, largest_only=True)
            if crops:
                return crops[0]
        return None

    def thumbnail(self, crop: Any, max_side: int = 240) -> bytes:
        if self._encoder is None:
            raise RuntimeError("no crop encoder configured")
        return self._encoder.jpeg(crop, max_side)

    def embed_crops(self, crops: Sequence[Any]) -> list[list[float]]:
        """L2-normalised embeddings of crops already cut out. CPU-bound."""
        return [l2_normalise(self._embedder.embed(c)) for c in crops]
