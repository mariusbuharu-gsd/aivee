"""Offline clip analysis (`--clip-epoch`): clip-position clock, progress file, waiting for
the retained state, and a FileSource that runs as fast as the CPU allows."""

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from aivee_contracts.geometry import CameraConfig, DeviceConfig, Zone
from aivee_contracts.rules import RuleSet
from aivee_edge.__main__ import parse
from aivee_edge.adapters.capture import FileSource
from aivee_edge.adapters.mqtt import MqttEdgeClient
from aivee_edge.app import clip_clock
from aivee_edge.progress import ProgressSource


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    """60 frames at 30 fps: a 2 s clip."""
    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 48))
    for i in range(60):
        writer.write(np.full((48, 64, 3), i, dtype=np.uint8))
    writer.release()
    return path


def test_file_source_knows_its_duration(clip: Path) -> None:
    source = FileSource(clip, target_fps=10)
    assert source.duration_s == pytest.approx(2.0, abs=0.05)
    source.close()


def test_file_source_does_not_pace_in_real_time(clip: Path) -> None:
    source = FileSource(clip, target_fps=30)
    start = time.monotonic()
    while source.read() is not None:
        pass
    assert time.monotonic() - start < 1.0  # a 2 s clip, decoded well under real time
    source.close()


def test_clip_clock_maps_positions_onto_the_epoch() -> None:
    epoch = datetime(2026, 11, 6, 18, 0, tzinfo=UTC)
    to_dt = clip_clock(epoch)
    assert to_dt(0.0) == epoch
    assert to_dt(75.5) == epoch + timedelta(seconds=75.5)


def test_cli_clip_mode_flags() -> None:
    s = parse(
        [
            "--source",
            "clip.mp4",
            "--clip-epoch",
            "2026-11-06T18:00:00+00:00",
            "--progress-file",
            "p.json",
            "--wait-config",
            "15",
        ]
    )
    assert s.clip_epoch == datetime(2026, 11, 6, 18, 0, tzinfo=UTC)
    assert (s.progress_file, s.config_wait_s) == ("p.json", 15.0)
    assert parse([]).clip_epoch is None


def test_progress_source_writes_position_and_done(clip: Path, tmp_path: Path) -> None:
    out = tmp_path / "progress.json"
    source = ProgressSource(FileSource(clip, target_fps=10), out, duration_s=2.0, every_s=0)
    frames = 0
    while source.read() is not None:
        frames += 1
        data = json.loads(out.read_text())
        assert data["done"] is False and data["frames"] == frames
    data = json.loads(out.read_text())
    assert data == {"frames": 20, "position_s": pytest.approx(1.9), "duration_s": 2.0, "done": True}
    source.close()


def _msg(topic: str, payload: bytes) -> Any:
    class Msg:
        pass

    m = Msg()
    m.topic = topic  # type: ignore[attr-defined]
    m.payload = payload  # type: ignore[attr-defined]
    return m


def test_wait_for_state_needs_this_camera_and_a_ruleset() -> None:
    edge = MqttEdgeClient("localhost", 1883, "u", "pw", "s1", "upload-01", camera_id="video-1")
    assert edge.wait_for_state(timeout=0.01) is False
    zone = Zone(id="t1", name="Masa 1", tag="table", polygon=[(0, 0), (1, 0), (1, 1)])
    other = DeviceConfig(
        device="upload-01", cameras=[CameraConfig(id="video-0", name="v0", source="f")]
    )
    edge._on_message(edge._client, None, _msg(edge.topics.config, other.model_dump_json().encode()))
    rules = RuleSet(device="upload-01", rules=[]).model_dump_json().encode()
    edge._on_message(edge._client, None, _msg(edge.topics.rules, rules))
    assert edge.wait_for_state(timeout=0.01) is False  # not this camera yet
    mine = DeviceConfig(
        device="upload-01",
        cameras=[CameraConfig(id="video-1", name="v1", source="f", zones=[zone])],
    )
    edge._on_message(edge._client, None, _msg(edge.topics.config, mine.model_dump_json().encode()))
    assert edge.wait_for_state(timeout=0.01) is True
