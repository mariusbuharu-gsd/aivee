import math

import pytest
from aivee_edge.domain.appearance import appearance_score, centroid, cosine, l2_normalise


def _unit_at(similarity: float) -> list[float]:
    """A unit vector whose cosine with (1, 0) equals `similarity`."""
    return [similarity, math.sqrt(1 - similarity**2)]


def test_cosine_basics() -> None:
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([1, 0], [-2, 0]) == pytest.approx(-1.0)
    assert cosine([3, 4], [6, 8]) == pytest.approx(1.0)


def test_cosine_with_zero_vector_is_zero() -> None:
    assert cosine([0, 0], [1, 0]) == 0.0


def test_cosine_rejects_mismatched_dimensions() -> None:
    with pytest.raises(ValueError):
        cosine([1, 0], [1, 0, 0])


def test_l2_normalise() -> None:
    assert l2_normalise([3, 4]) == pytest.approx([0.6, 0.8])
    assert l2_normalise([0, 0]) == [0.0, 0.0]


def test_centroid_is_normalised_mean() -> None:
    assert centroid([[1, 0], [0, 1]]) == pytest.approx([math.sqrt(0.5), math.sqrt(0.5)])
    assert centroid([[2, 0]]) == pytest.approx([1.0, 0.0])


def test_centroid_rejects_empty_and_ragged_input() -> None:
    with pytest.raises(ValueError):
        centroid([])
    with pytest.raises(ValueError):
        centroid([[1, 0], [1, 0, 0]])


def test_no_profiles_gives_none() -> None:
    assert appearance_score([1, 0], []) is None


@pytest.mark.parametrize(
    ("similarity", "expected"),
    [(0.30, 0.0), (0.70, 0.0), (0.76, 0.5), (0.82, 1.0), (0.95, 1.0)],
)
def test_similarity_maps_linearly_between_thresholds(similarity: float, expected: float) -> None:
    assert appearance_score(_unit_at(similarity), [[1, 0]]) == pytest.approx(expected)


def test_best_profile_wins() -> None:
    profiles = [[0, 1], [1, 0]]
    assert appearance_score(_unit_at(0.82), profiles) == pytest.approx(1.0)


def test_defaults_separate_the_measured_live_crops() -> None:
    """CLIP ViT-B-32 crops vs a 9-photo profile: staff 0.82-0.91, seated guests 0.60-0.64."""
    profile = [[1, 0]]
    assert appearance_score(_unit_at(0.82), profile) == pytest.approx(1.0)
    assert appearance_score(_unit_at(0.91), profile) == pytest.approx(1.0)
    assert appearance_score(_unit_at(0.64), profile) == 0.0
    assert appearance_score(_unit_at(0.60), profile) == 0.0


def test_thresholds_are_configurable() -> None:
    score = appearance_score(_unit_at(0.5), [[1, 0]], low=0.4, high=0.6)
    assert score == pytest.approx(0.5)


def test_invalid_thresholds_are_rejected() -> None:
    with pytest.raises(ValueError):
        appearance_score([1, 0], [[1, 0]], low=0.3, high=0.3)
