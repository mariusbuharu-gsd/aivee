"""Appearance similarity of a person crop to staff profiles (uniform, apron, colours).

Embeddings come from an image model (CLIP ViT-B-32 person crops) in the adapters;
here they are plain lists of floats. Profiles are L2-normalised centroids of the
owner's staff examples. Raw CLIP cosines between crops are small, so the best cosine
is mapped onto [0, 1] between two thresholds.
"""

import math
from collections.abc import Sequence

Vector = Sequence[float]

LOW_SIMILARITY = 0.18
"""Best cosine at or below this → appearance score 0."""
HIGH_SIMILARITY = 0.30
"""Best cosine at or above this → appearance score 1."""


def _check_same_dim(a: Vector, b: Vector) -> None:
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} != {len(b)}")


def _norm(v: Vector) -> float:
    return math.sqrt(sum(x * x for x in v))


def cosine(a: Vector, b: Vector) -> float:
    """Cosine similarity; 0.0 if either vector is zero."""
    _check_same_dim(a, b)
    na, nb = _norm(a), _norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)


def l2_normalise(v: Vector) -> list[float]:
    """Unit-length copy of `v`; a zero vector stays zero."""
    n = _norm(v)
    return [float(x) / n for x in v] if n else [0.0 for _ in v]


def centroid(vectors: Sequence[Vector]) -> list[float]:
    """L2-normalised mean of the given vectors (a staff profile)."""
    if not vectors:
        raise ValueError("centroid of no vectors")
    dim = len(vectors[0])
    for v in vectors:
        _check_same_dim(vectors[0], v)
    mean = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
    return l2_normalise(mean)


def appearance_score(
    embedding: Vector,
    profiles: Sequence[Vector],
    *,
    low: float = LOW_SIMILARITY,
    high: float = HIGH_SIMILARITY,
) -> float | None:
    """Best cosine to any profile, mapped linearly from [low, high] to [0, 1].

    Returns None when there are no profiles, so fusion can ignore appearance.
    """
    if high <= low:
        raise ValueError("high must be greater than low")
    if not profiles:
        return None
    best = max(cosine(embedding, p) for p in profiles)
    return max(0.0, min(1.0, (best - low) / (high - low)))
