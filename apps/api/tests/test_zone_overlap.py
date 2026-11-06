"""Zone overlap is pure geometry: interiors that share an area, not edges that touch."""

from aivee_api.zones.overlap import overlap_warnings_ro, polygons_overlap
from aivee_contracts.geometry import Point, Zone


def square(x: float, y: float, size: float = 0.2) -> list[Point]:
    return [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]


def zone(zone_id: str, name: str, polygon: list[Point], tag: str = "table") -> Zone:
    return Zone(id=zone_id, name=name, tag=tag, polygon=polygon)


def test_partly_overlapping_squares_overlap() -> None:
    assert polygons_overlap(square(0.1, 0.1), square(0.2, 0.2))


def test_apart_squares_do_not_overlap() -> None:
    assert not polygons_overlap(square(0.1, 0.1), square(0.5, 0.5))


def test_squares_sharing_an_edge_or_a_corner_do_not_overlap() -> None:
    assert not polygons_overlap(square(0.1, 0.1), square(0.3, 0.1))
    assert not polygons_overlap(square(0.1, 0.1), square(0.3, 0.3))


def test_identical_and_nested_polygons_overlap() -> None:
    assert polygons_overlap(square(0.1, 0.1), square(0.1, 0.1))
    assert polygons_overlap(square(0.1, 0.1, 0.5), square(0.2, 0.2, 0.1))
    assert polygons_overlap(square(0.2, 0.2, 0.1), square(0.1, 0.1, 0.5))


def test_cross_shaped_overlap_without_vertices_inside() -> None:
    wide = [(0.1, 0.4), (0.9, 0.4), (0.9, 0.6), (0.1, 0.6)]
    tall = [(0.4, 0.1), (0.6, 0.1), (0.6, 0.9), (0.4, 0.9)]
    assert polygons_overlap(wide, tall)


def test_offset_squares_with_collinear_edges_overlap() -> None:
    assert polygons_overlap(square(0.0, 0.0, 0.4), square(0.0, 0.2, 0.4))


def test_concave_polygon_whose_notch_holds_the_other_does_not_overlap() -> None:
    u_shape = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.7, 0.9), (0.7, 0.3), (0.3, 0.3), (0.3, 0.9)]
    u_shape.append((0.1, 0.9))
    inside_notch = square(0.4, 0.5, 0.2)
    assert not polygons_overlap(u_shape, inside_notch)
    assert polygons_overlap(u_shape, square(0.2, 0.5, 0.2))


def test_triangles() -> None:
    a = [(0.0, 0.0), (0.4, 0.0), (0.0, 0.4)]
    assert not polygons_overlap(a, [(0.4, 0.0), (0.4, 0.4), (0.0, 0.4)])  # share the diagonal
    assert polygons_overlap(a, [(0.1, 0.1), (0.5, 0.1), (0.1, 0.5)])


def test_warnings_name_each_overlapping_pair_in_order() -> None:
    zones = [
        zone("z1", "Masa 1", square(0.1, 0.1)),
        zone("z2", "Masa 2", square(0.2, 0.2)),
        zone("z3", "Intrare", square(0.7, 0.7), tag="entrance"),
        zone("z4", "Bar", square(0.25, 0.15), tag="staff"),
    ]
    assert overlap_warnings_ro(zones) == [
        "Zonele «Masa 1» și «Masa 2» se suprapun",
        "Zonele «Masa 1» și «Bar» se suprapun",
        "Zonele «Masa 2» și «Bar» se suprapun",
    ]


def test_no_warnings_for_separate_zones() -> None:
    assert overlap_warnings_ro([zone("z1", "Masa 1", square(0.1, 0.1))]) == []
    assert overlap_warnings_ro([]) == []
