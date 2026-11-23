"""The edge box follows the cameras the dashboard configures, without restarting the others."""

from typing import Any

import pytest
from aivee_contracts.geometry import CameraConfig, DeviceConfig
from aivee_edge.fleet import CameraFleet
from aivee_edge.supervisor import CameraRun


class Client:
    def __init__(self) -> None:
        self.config: DeviceConfig | None = None
        self.dropped: list[str] = []

    def device_config(self) -> DeviceConfig | None:
        return self.config

    def drop_camera(self, camera_id: str) -> None:
        self.dropped.append(camera_id)


class Sup:
    def __init__(self) -> None:
        self.added: list[str] = []
        self.removed: list[str] = []

    def add(self, cam: CameraRun) -> None:
        self.added.append(cam.camera_id)

    def remove(self, camera_id: str) -> None:
        self.removed.append(camera_id)


class Health:
    def __init__(self) -> None:
        self.watched: dict[str, object] = {}

    def add(self, camera_id: str, source: object) -> None:
        self.watched[camera_id] = source

    def remove(self, camera_id: str) -> None:
        self.watched.pop(camera_id, None)


def _config(*cams: tuple[str, str]) -> DeviceConfig:
    return DeviceConfig(
        device="edge-01", cameras=[CameraConfig(id=i, name=i, source=s) for i, s in cams]
    )


@pytest.fixture
def world() -> tuple[CameraFleet, Client, Sup, Health, list[tuple[str, str]]]:
    client, sup, health = Client(), Sup(), Health()
    built: list[tuple[str, str]] = []

    def build(cam: CameraConfig) -> CameraRun:
        if "broken" in cam.source:
            raise RuntimeError("no models")
        built.append((cam.id, cam.source))
        return CameraRun(cam.id, object(), f"source of {cam.id}")  # type: ignore[arg-type]

    return CameraFleet(sup, client, health, build), client, sup, health, built


def test_nothing_runs_before_the_config_arrives(world: Any) -> None:
    fleet, _client, sup, _health, built = world
    fleet.reconcile()
    assert built == [] and sup.added == [] and fleet.running() == {}


def test_cameras_start_stop_and_restart_with_the_config(
    world: Any, caplog: pytest.LogCaptureFixture
) -> None:
    fleet, client, sup, health, built = world
    client.config = _config(
        ("cam-01", "rtsp://admin:s3cr3t@10.0.0.21/stream2"),
        ("cam-02", "rtsp://10.0.0.22/stream2"),
        ("phone", "mqtt-frames://phone"),  # a cloud camera: not this box's job
    )
    with caplog.at_level("INFO"):
        fleet.reconcile()
    assert sup.added == ["cam-01", "cam-02"]
    assert set(health.watched) == {"cam-01", "cam-02"}
    assert "s3cr3t" not in caplog.text and "rtsp://admin:***@10.0.0.21" in caplog.text

    fleet.reconcile()  # same config: nothing happens
    assert len(built) == 2 and sup.removed == []

    client.config = _config(
        ("cam-02", "rtsp://10.0.0.22/stream1"), ("cam-03", "rtsp://10.0.0.23/stream2")
    )
    fleet.reconcile()
    assert sup.removed == ["cam-01", "cam-02"] and client.dropped == ["cam-01", "cam-02"]
    assert sup.added == ["cam-01", "cam-02", "cam-02", "cam-03"]
    assert fleet.running() == {
        "cam-02": "rtsp://10.0.0.22/stream1",
        "cam-03": "rtsp://10.0.0.23/stream2",
    }
    assert set(health.watched) == {"cam-02", "cam-03"}

    client.config = _config()
    fleet.reconcile()
    assert fleet.running() == {} and health.watched == {}


def test_a_camera_that_fails_to_start_is_retried_only_with_a_new_source(
    world: Any, caplog: pytest.LogCaptureFixture
) -> None:
    fleet, client, sup, _health, _built = world
    client.config = _config(("cam-01", "rtsp://broken/1"), ("cam-02", "rtsp://ok/1"))
    with caplog.at_level("ERROR"):
        fleet.reconcile()
        fleet.reconcile()
    assert sup.added == ["cam-02"]
    assert caplog.text.count("camera_start_failed camera=cam-01") == 1
    assert client.dropped == ["cam-01"]
    client.config = _config(("cam-01", "rtsp://fixed/1"), ("cam-02", "rtsp://ok/1"))
    fleet.reconcile()
    assert sup.added == ["cam-02", "cam-01"]


def test_stop_all_stops_every_running_camera(world: Any) -> None:
    fleet, client, sup, _health, _built = world
    client.config = _config(("cam-01", "rtsp://a/1"), ("cam-02", "rtsp://b/1"))
    fleet.reconcile()
    fleet.stop_all()
    assert sup.removed == ["cam-01", "cam-02"] and fleet.running() == {}
