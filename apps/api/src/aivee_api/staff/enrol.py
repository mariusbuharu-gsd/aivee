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
    def crops(self, frame: Any) -> list[Any]: ...


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
        self, decoder: FrameDecoder, cropper: PersonCropper, embedder: ImageEmbedder
    ) -> None:
        self._decoder = decoder
        self._cropper = cropper
        self._embedder = embedder

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
