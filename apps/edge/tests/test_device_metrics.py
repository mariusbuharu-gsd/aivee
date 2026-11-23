"""One Metrics per device from several cameras: the API keeps the latest Metrics per device,
so per-camera messages on the same topic would overwrite each other."""

from aivee_contracts.events import Metrics
from aivee_edge.metrics import DeviceMetrics


def _m(fps: float, verified: float = 0.5, cpu: float = 40.0) -> Metrics:
    return Metrics(device="edge-01", fps=fps, verified_ratio=verified, cpu_percent=cpu)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_one_device_metrics_per_interval_with_the_slowest_camera_fps() -> None:
    clock = Clock()
    combined = DeviceMetrics("edge-01", ["cam-01", "cam-02"], interval_s=5, clock=clock)
    clock.now = 105.0
    out = combined.add("cam-01", _m(10.0, verified=0.4, cpu=30))
    assert out is None  # cam-02 has not reported this interval yet: wait for it
    clock.now = 105.5
    out = combined.add("cam-02", _m(8.0, verified=0.6, cpu=35))
    assert out == Metrics(device="edge-01", fps=8.0, verified_ratio=0.5, cpu_percent=35)
    clock.now = 106.0
    assert combined.add("cam-01", _m(10.0)) is None  # same interval


def test_a_silent_camera_counts_as_zero_fps() -> None:
    clock = Clock()
    combined = DeviceMetrics("edge-01", ["cam-01", "cam-02"], interval_s=5, clock=clock)
    published = []
    for step in range(1, 9):  # cam-02 never reports (down)
        clock.now = 100.0 + 5 * step
        if (m := combined.add("cam-01", _m(10.0, verified=0.2))) is not None:
            published.append(m)
    assert published, "the healthy camera keeps the device's metrics flowing"
    assert all(m.fps == 0.0 for m in published)
    assert published[-1].verified_ratio == 0.2


def test_a_single_camera_passes_through() -> None:
    clock = Clock()
    combined = DeviceMetrics("edge-01", ["cam-01"], interval_s=5, clock=clock)
    clock.now = 105.0
    assert combined.add("cam-01", _m(9.5)) == _m(9.5)


def test_samples_from_unknown_cameras_are_ignored() -> None:
    clock = Clock()
    combined = DeviceMetrics("edge-01", ["cam-01"], interval_s=5, clock=clock)
    clock.now = 105.0
    assert combined.add("cam-99", _m(1.0)) is None
