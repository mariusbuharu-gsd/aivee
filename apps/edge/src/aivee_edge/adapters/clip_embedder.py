"""CLIP appearance embeddings of person crops (for staff/guest role scoring)."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any, Protocol


class Embedder(Protocol):
    def embed(self, crop: Any) -> list[float]: ...


def l2_normalise(vec: Iterable[float]) -> list[float]:
    values = [float(v) for v in vec]
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values] if norm > 0 else values


class ClipEmbedder:
    """open_clip image encoder on CPU. `crop` is a BGR uint8 array (OpenCV layout)."""

    def __init__(
        self, model: str = "ViT-B-32", pretrained: str = "laion2b_s34b_b79k", threads: int = 0
    ) -> None:
        import open_clip
        import torch

        if threads > 0:
            torch.set_num_threads(threads)
        self._torch = torch
        self._model, _, self._preprocess = open_clip.create_model_and_transforms(
            model, pretrained=pretrained, device="cpu"
        )
        self._model.eval()

    def embed(self, crop: Any) -> list[float]:
        from PIL import Image

        rgb = crop[:, :, ::-1]
        tensor = self._preprocess(Image.fromarray(rgb)).unsqueeze(0)
        with self._torch.inference_mode():
            features = self._model.encode_image(tensor)[0]
        return l2_normalise(features.tolist())


class RateLimitedEmbedder:
    """Embeds each track at most once per `interval_s`; otherwise returns the cached vector."""

    def __init__(self, inner: Embedder, interval_s: float = 2.0) -> None:
        self._inner = inner
        self._interval = interval_s
        self._cache: dict[int, tuple[float, list[float]]] = {}

    def embed(self, track_id: int, crop: Any, ts: float) -> list[float]:
        cached = self._cache.get(track_id)
        if cached is not None and ts - cached[0] < self._interval:
            return cached[1]
        vec = self._inner.embed(crop)
        self._cache[track_id] = (ts, vec)
        return vec

    def due(self, track_id: int, ts: float) -> bool:
        """True when `embed` would run the model (lets callers skip cropping)."""
        cached = self._cache.get(track_id)
        return cached is None or ts - cached[0] >= self._interval

    def cached(self, track_id: int) -> list[float] | None:
        entry = self._cache.get(track_id)
        return None if entry is None else entry[1]

    def forget(self, active_ids: Iterable[int]) -> None:
        """Drop cache entries for tracks that are gone."""
        keep = set(active_ids)
        for tid in [t for t in self._cache if t not in keep]:
            del self._cache[tid]
