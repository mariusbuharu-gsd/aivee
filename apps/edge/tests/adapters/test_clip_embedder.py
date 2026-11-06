import math
from typing import Any

import numpy as np
import pytest
from aivee_edge.adapters.clip_embedder import RateLimitedEmbedder, l2_normalise


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls = 0

    def embed(self, crop: Any) -> list[float]:
        self.calls += 1
        return [float(self.calls), 0.0]


def test_l2_normalise() -> None:
    assert l2_normalise([3, 4]) == [0.6, 0.8]
    assert l2_normalise([0, 0]) == [0.0, 0.0]


def test_rate_limited_embeds_each_track_at_most_every_two_seconds() -> None:
    fake = FakeEmbedder()
    emb = RateLimitedEmbedder(fake, interval_s=2.0)
    assert emb.embed(1, None, ts=0.0) == [1.0, 0.0]
    assert emb.embed(1, None, ts=1.9) == [1.0, 0.0]  # cached
    assert fake.calls == 1
    assert emb.embed(2, None, ts=1.9) == [2.0, 0.0]  # other track is independent
    assert emb.embed(1, None, ts=2.0) == [3.0, 0.0]  # interval elapsed
    assert fake.calls == 3


def test_due_cached_and_forget() -> None:
    emb = RateLimitedEmbedder(FakeEmbedder(), interval_s=2.0)
    assert emb.due(1, 0.0) and emb.cached(1) is None
    emb.embed(1, None, 0.0)
    emb.embed(2, None, 0.0)
    assert not emb.due(1, 1.0) and emb.due(1, 2.5)
    emb.forget([2])
    assert emb.cached(1) is None and emb.cached(2) is not None


@pytest.mark.integration
def test_real_clip_embedding_is_unit_length() -> None:
    from aivee_edge.adapters.clip_embedder import ClipEmbedder

    vec = ClipEmbedder().embed(np.zeros((128, 64, 3), dtype=np.uint8))
    assert len(vec) == 512
    assert math.isclose(math.sqrt(sum(v * v for v in vec)), 1.0, rel_tol=1e-4)
