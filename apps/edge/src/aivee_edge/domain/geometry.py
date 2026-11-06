"""Plane geometry on normalised image coordinates."""

from aivee_contracts.geometry import Point

from aivee_edge.domain.observation import BBox


def point_in_polygon(p: Point, poly: list[Point]) -> bool:
    """Ray casting: count edge crossings of a horizontal ray from `p`."""
    x, y = p
    inside = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def foot_point(bbox: BBox) -> Point:
    """Bottom-centre of a person box: a person "is" where their feet are."""
    x1, _, x2, y2 = bbox
    return ((x1 + x2) / 2, y2)


def box_centre(bbox: BBox) -> Point:
    """Centre of an object box."""
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2, (y1 + y2) / 2)
