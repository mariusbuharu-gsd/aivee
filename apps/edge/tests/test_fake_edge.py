"""tools/fake_edge.py scenarios through the real pipeline, without a broker."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

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
