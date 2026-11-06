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
    assert states == [("opened", rule_id, zone), ("closed", rule_id, zone)], states


@pytest.mark.parametrize(
    ("name", "opens_at", "closes_at"),
    [("unattended", 60, 90), ("hand", 5, 10), ("queue", 10, 30), ("uncleared", 75, 85)],
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
    opened, closed = (e.at.timestamp() for e in rec.alerts)
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
        ("opened", rule_id, "cam-sala", zone),
        ("closed", rule_id, "cam-sala", zone),
    ]


@pytest.mark.parametrize("name", ["unattended", "hand", "uncleared"])
def test_fewer_retained_tables_wrap_around(name: str) -> None:
    """With one table every table scenario happens there (the waiter still stays away)."""
    [rule_id] = fake_edge.SCENARIOS[name].expects
    assert _run_on(_retained_camera(tables=1), name) == [
        ("opened", rule_id, "cam-sala", "z-table-1"),
        ("closed", rule_id, "cam-sala", "z-table-1"),
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
