"""Do two drawn zones share an area? Pure geometry, exact for any simple polygon.

Two polygons overlap when their interiors meet; edges or corners that only touch do not
count (tables drawn side by side are fine). The plane is cut into horizontal slabs at every
vertex and every edge crossing: inside a slab no edge starts, ends or crosses another, so
the polygons' cross-sections at the slab's middle tell whether they overlap anywhere in it.
"""

from collections.abc import Sequence
from itertools import combinations, pairwise

from aivee_contracts.geometry import Point, Zone

_EPS = 1e-9

Polygon = Sequence[Point]


def _edges(poly: Polygon) -> list[tuple[Point, Point]]:
    return [(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))]


def _crossing_y(a: tuple[Point, Point], b: tuple[Point, Point]) -> float | None:
    """The y of the point where two segments meet (touching included), else None."""
    (x1, y1), (x2, y2) = a
    (x3, y3), (x4, y4) = b
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < _EPS:
        return None  # parallel or collinear: their end points are already slab bounds
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    u = ((x1 - x3) * (y1 - y2) - (y1 - y3) * (x1 - x2)) / den
    if -_EPS <= t <= 1 + _EPS and -_EPS <= u <= 1 + _EPS:
        return y1 + t * (y2 - y1)
    return None


def _section(poly: Polygon, y: float) -> list[tuple[float, float]]:
    """The x intervals of the polygon's interior on the line at height y (even-odd)."""
    xs = sorted(
        x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        for (x1, y1), (x2, y2) in _edges(poly)
        if (y1 < y) != (y2 < y)
    )
    return list(zip(xs[::2], xs[1::2], strict=True))


def _sections_overlap(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> bool:
    return any(min(a1, b1) - max(a0, b0) > _EPS for a0, a1 in a for b0, b1 in b)


def polygons_overlap(a: Polygon, b: Polygon) -> bool:
    ys = {p[1] for p in (*a, *b)}
    for ea in _edges(a):
        for eb in _edges(b):
            y = _crossing_y(ea, eb)
            if y is not None:
                ys.add(y)
    bounds = sorted(ys)
    for lo, hi in pairwise(bounds):
        if hi - lo <= _EPS:
            continue
        mid = (lo + hi) / 2
        if _sections_overlap(_section(a, mid), _section(b, mid)):
            return True
    return False


def overlap_warnings_ro(zones: Sequence[Zone]) -> list[str]:
    """ "Zonele «Masa 1» și «Masa 2» se suprapun" for every overlapping pair, in order."""
    return [
        f"Zonele «{z1.name}» și «{z2.name}» se suprapun"
        for z1, z2 in combinations(zones, 2)
        if polygons_overlap(z1.polygon, z2.polygon)
    ]
