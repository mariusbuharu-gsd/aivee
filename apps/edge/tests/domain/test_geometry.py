import pytest
from aivee_edge.domain.geometry import box_centre, foot_point, point_in_polygon

SQUARE = [(0.2, 0.2), (0.6, 0.2), (0.6, 0.6), (0.2, 0.6)]
# An "L" shape: the notch at the top-right is outside.
L_SHAPE = [(0.0, 0.0), (0.4, 0.0), (0.4, 0.6), (1.0, 0.6), (1.0, 1.0), (0.0, 1.0)]


def test_point_inside_square() -> None:
    assert point_in_polygon((0.4, 0.4), SQUARE)


def test_point_outside_square() -> None:
    assert not point_in_polygon((0.7, 0.4), SQUARE)
    assert not point_in_polygon((0.4, 0.1), SQUARE)


def test_point_in_concave_polygon() -> None:
    assert point_in_polygon((0.2, 0.3), L_SHAPE)
    assert point_in_polygon((0.8, 0.8), L_SHAPE)
    assert not point_in_polygon((0.8, 0.3), L_SHAPE)


def test_foot_point_is_bottom_centre_of_box() -> None:
    assert foot_point((0.2, 0.1, 0.4, 0.9)) == pytest.approx((0.3, 0.9))


def test_box_centre() -> None:
    assert box_centre((0.2, 0.2, 0.4, 0.6)) == pytest.approx((0.3, 0.4))
