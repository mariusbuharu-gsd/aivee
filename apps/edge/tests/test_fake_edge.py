"""tools/fake_edge.py scenarios through the real pipeline, without a broker."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

TOOL = Path(__file__).resolve().parents[3] / "tools" / "fake_edge.py"


def load_fake_edge() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fake_edge", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["fake_edge"] = module
    spec.loader.exec_module(module)
    return module


fake_edge = load_fake_edge()


def _lifecycle(name: str) -> list[str]:
    """Only the unattended scenario has a waiter who comes and stays (→ arrived)."""
    return ["opened", "arrived", "closed"] if name == "unattended" else ["opened", "closed"]


@pytest.mark.parametrize(
    ("name", "zone"),
    [
        ("unattended", "masa-1"),
        ("hand", "masa-2"),
        ("queue", "intrare"),
        ("uncleared", "masa-3"),
    ],
)
def test_scenario_opens_then_closes_its_alert(name: str, zone: str) -> None:
    scenario = fake_edge.SCENARIOS[name]
    config = fake_edge.FallbackConfig(None, "cam-01", force_demo=True)
    rec = fake_edge.run_scenario(
        scenario, None, config, device="edge-01", camera_id="cam-01", speed=0
    )
    states = [(e.state, e.rule_id, e.zone_id) for e in rec.alerts]
    [rule_id] = scenario.expects
    assert states == [(s, rule_id, zone) for s in _lifecycle(name)], states


@pytest.mark.parametrize(
    ("name", "opens_at", "closes_at"),
    [("unattended", 60, 95), ("hand", 5, 10), ("queue", 10, 30), ("uncleared", 75, 85)],
)
def test_scenario_timing_on_simulated_clock(name: str, opens_at: float, closes_at: float) -> None:
    """Same run, but with the engine clock on simulated time to check when things happen."""
    from aivee_edge.pipeline import EdgePipeline

    scenario = fake_edge.SCENARIOS[name]
    rec = fake_edge.Recorder()
    pipeline = EdgePipeline(
        fake_edge.ScenarioSource(scenario, speed=0),
        fake_edge.EchoDetector(),
        rec,
        fake_edge.FallbackConfig(None, "cam-01", force_demo=True),
        device="edge-01",
        camera_id="cam-01",
        pose=fake_edge.ScriptedPose(),
        cpu=lambda: 0.0,
    )
    pipeline.run()
    opened, closed = (e.at.timestamp() for e in (rec.alerts[0], rec.alerts[-1]))
    assert opens_at <= opened <= opens_at + 2
    assert closes_at <= closed <= closes_at + 2


# -- retained layout: the dashboard's own camera and zone ids --------------------------------


def _square(zone_id: str, name: str, tag: str, x: float, y: float, size: float = 0.12) -> Any:
    from aivee_contracts.geometry import Zone

    return Zone(
        id=zone_id,
        name=name,
        tag=tag,
        polygon=[(x, y), (x + size, y), (x + size, y + size), (x, y + size)],
    )


def _retained_camera(tables: int = 4) -> Any:
    from aivee_contracts.geometry import CameraConfig

    spots = [(0.10, 0.30), (0.75, 0.30), (0.10, 0.80), (0.75, 0.80)]
    zones = [
        _square(f"z-table-{i + 1}", f"Masa {i + 1} (sala)", "table", *spots[i])
        for i in range(tables)
    ]
    zones.append(_square("z-door", "Ușa", "entrance", 0.45, 0.25, 0.1))
    return CameraConfig(id="cam-sala", name="Sala", source="rtsp://x", zones=zones)


def _run_on(camera: Any, name: str) -> list[tuple[str, str, str, str]]:
    layout = fake_edge.Layout.from_camera(camera)
    config = fake_edge.FallbackConfig(None, camera.id, force_demo=False, layout=layout)
    rec = fake_edge.run_scenario(
        fake_edge.SCENARIOS[name],
        None,
        config,
        device="edge-01",
        camera_id=camera.id,
        speed=0,
        layout=layout,
    )
    return [(e.state, e.rule_id, e.camera_id, e.zone_id) for e in rec.alerts]


@pytest.mark.parametrize(
    ("name", "zone"),
    [
        ("unattended", "z-table-1"),
        ("hand", "z-table-2"),
        ("queue", "z-door"),
        ("uncleared", "z-table-3"),
    ],
)
def test_scenarios_run_on_the_retained_zones(name: str, zone: str) -> None:
    [rule_id] = fake_edge.SCENARIOS[name].expects
    assert _run_on(_retained_camera(), name) == [
        (s, rule_id, "cam-sala", zone) for s in _lifecycle(name)
    ]


@pytest.mark.parametrize("name", ["unattended", "hand", "uncleared"])
def test_fewer_retained_tables_wrap_around(name: str) -> None:
    """With one table every table scenario happens there (the waiter still stays away)."""
    [rule_id] = fake_edge.SCENARIOS[name].expects
    assert _run_on(_retained_camera(tables=1), name) == [
        (s, rule_id, "cam-sala", "z-table-1") for s in _lifecycle(name)
    ]


def test_layout_keeps_demo_places_for_missing_tags() -> None:
    from aivee_contracts.geometry import CameraConfig

    camera = CameraConfig(
        id="c", name="c", source="x", zones=[_square("t", "T", "table", 0.2, 0.2)]
    )
    layout = fake_edge.Layout.from_camera(camera)
    assert layout.camera.id == "c" and layout.camera.zones[0] == camera.zones[0]
    assert layout.places["masa-4"].id == "t"
    assert layout.places["intrare"].id == "demo-intrare"  # the entrance is a demo zone
    assert layout.places["intrare"].polygon == fake_edge.ZONE["intrare"].polygon
    assert layout.missing_tags == ["staff", "entrance"]
    # masa-1 is the retained table; every other demo spot becomes a demo-* zone
    extra = {z.id for z in layout.camera.zones} - {"t"}
    assert extra == {"demo-masa-2", "demo-masa-3", "demo-masa-4", "demo-bucatarie", "demo-intrare"}


def test_pick_camera_prefers_the_requested_id_then_the_first_with_zones() -> None:
    from aivee_contracts.geometry import CameraConfig, DeviceConfig

    empty = CameraConfig(id="empty", name="e", source="x")
    sala = _retained_camera()
    config = DeviceConfig(device="edge-01", cameras=[empty, sala])
    assert fake_edge.pick_camera(config, None) == sala
    assert fake_edge.pick_camera(config, "cam-sala") == sala
    assert fake_edge.pick_camera(config, "other") is None
    assert fake_edge.pick_camera(DeviceConfig(device="edge-01", cameras=[empty]), None) is None
    assert fake_edge.pick_camera(None, None) is None


def test_scripted_boxes_stay_normalised_near_the_edges() -> None:
    from aivee_contracts.geometry import CameraConfig

    top = CameraConfig(
        id="c", name="c", source="x", zones=[_square("t", "T", "table", 0.0, 0.0, 0.05)]
    )
    layout = fake_edge.Layout.from_camera(top)
    tracks, _ = fake_edge.SCENARIOS["unattended"].script(0.0, layout)
    for t in tracks:
        assert all(0 <= c <= 1 for c in t.bbox), t.bbox


def test_unattended_waiter_arrives_after_staying_five_seconds() -> None:
    from aivee_edge.pipeline import EdgePipeline

    rec = fake_edge.Recorder()
    EdgePipeline(
        fake_edge.ScenarioSource(fake_edge.SCENARIOS["unattended"], speed=0),
        fake_edge.EchoDetector(),
        rec,
        fake_edge.FallbackConfig(None, "cam-01", force_demo=True),
        device="edge-01",
        camera_id="cam-01",
        pose=fake_edge.ScriptedPose(),
        cpu=lambda: 0.0,
    ).run()
    arrived = next(e for e in rec.alerts if e.state == "arrived")
    assert 95 <= arrived.at.timestamp() <= 96  # the waiter reaches Masa 1 at 90


# -- overlapping retained tables: the waiter serves the guests' own zone ----------------------


def _redrawn_tables(tables: int, overlap: float) -> Any:
    """cam-01 with "Masa 1" and, for two tables, a redrawn "Masa 2" overlapping it."""
    from aivee_contracts.geometry import CameraConfig

    zones = [_square("z-masa-1", "Masa 1", "table", 0.10, 0.30, 0.25)]
    if tables == 2:
        zones.append(_square("z-masa-2", "Masa 2", "table", 0.35 - overlap, 0.32, 0.25))
    return CameraConfig(id="cam-01", name="Sala", source="rtsp://x", zones=zones)


@pytest.mark.parametrize(
    ("tables", "overlap"),
    [(1, 0.0), (2, 0.05), (2, 0.15)],
    ids=["one-table", "two-tables-slight-overlap", "two-tables-guests-in-overlap"],
)
def test_unattended_waiter_arrives_at_the_guests_zone(tables: int, overlap: float) -> None:
    camera = _redrawn_tables(tables, overlap)
    assert _run_on(camera, "unattended") == [
        (s, "demo-unattended", "cam-01", "z-masa-1") for s in _lifecycle("unattended")
    ]


def test_unattended_people_stand_in_the_guests_zone_only() -> None:
    from aivee_edge.domain.geometry import foot_point, point_in_polygon

    camera = _redrawn_tables(2, 0.15)
    masa_1, masa_2 = camera.zones
    layout = fake_edge.Layout.from_camera(camera)
    assert layout.places["masa-1"] == masa_1
    for t in (0.0, 95.0):  # the guests, then the guests and the waiter who came
        tracks, _ = fake_edge.SCENARIOS["unattended"].script(t, layout)
        for track in tracks:
            foot = foot_point(track.bbox)
            assert point_in_polygon(foot, masa_1.polygon), (t, track)
            assert not point_in_polygon(foot, masa_2.polygon), (t, track)


def test_waiter_round_never_uses_a_zone_overlapping_the_guests() -> None:
    camera = _redrawn_tables(2, 0.05)
    layout = fake_edge.Layout.from_camera(camera)
    masa_1 = camera.zones[0]
    zones = layout.camera.zones
    stops = [layout.waypoints[p] for p in ("masa-2", "masa-3", "masa-4")]
    stops = [z for z in stops if z in zones]
    assert len(stops) >= 2 and all(not fake_edge._overlaps(z, masa_1) for z in stops)
    assert all(z.id.startswith("demo-") for z in stops)  # behaviour-only stand-ins
