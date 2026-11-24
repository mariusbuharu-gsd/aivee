"""Entry point wiring without cameras, models or a broker."""

import importlib
from typing import Any

import numpy as np
import pytest
from aivee_edge import app
from aivee_edge.__main__ import parse
from aivee_edge.domain.role import StaffWeights
from aivee_edge.settings import EdgeSettings


def test_cli_overrides_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MQTT_EDGE_USER", "edge-07")
    s = parse(["--source", "clip.mp4", "--fps", "5", "--no-pose", "--appearance", "--loop"])
    assert (s.source, s.target_fps, s.pose_model, s.appearance, s.loop_file) == (
        "clip.mp4",
        5.0,
        "",
        True,
        True,
    )
    assert s.device == "edge-07"  # device id follows the MQTT user (ACL)


def test_rotate_flag_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert parse([]).rotate == 0
    assert parse(["--rotate", "90"]).rotate == 90
    monkeypatch.setenv("ROTATE", "270")
    assert parse([]).rotate == 270
    with pytest.raises(SystemExit):
        parse(["--rotate", "45"])


def test_rotate_setting_accepts_only_right_angles() -> None:
    with pytest.raises(ValueError):
        EdgeSettings(rotate=45, _env_file=None)  # type: ignore[call-arg]


def test_appearance_thresholds_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    defaults = EdgeSettings(_env_file=None)  # type: ignore[call-arg]
    assert (defaults.appearance_low, defaults.appearance_high) == (0.70, 0.82)
    monkeypatch.setenv("APPEARANCE_LOW", "0.65")
    monkeypatch.setenv("APPEARANCE_HIGH", "0.8")
    s = EdgeSettings(_env_file=None)  # type: ignore[call-arg]
    assert (s.appearance_low, s.appearance_high) == (0.65, 0.8)
    assert app.pipeline_tuning(s)["appearance_low"] == 0.65
    assert app.pipeline_tuning(s)["appearance_high"] == 0.8


def test_staff_weights_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    defaults = app.pipeline_tuning(EdgeSettings(_env_file=None))  # type: ignore[call-arg]
    assert defaults["staff_weights"] == StaffWeights(0.60, 0.25, 0.15)
    monkeypatch.setenv("STAFF_W_APPEARANCE", "0.5")
    monkeypatch.setenv("STAFF_W_STANDING", "0.3")
    monkeypatch.setenv("STAFF_W_BEHAVIOUR", "0.2")
    tuned = app.pipeline_tuning(EdgeSettings(_env_file=None))  # type: ignore[call-arg]
    assert tuned["staff_weights"] == StaffWeights(0.5, 0.3, 0.2)


def test_staff_weights_must_be_non_negative_and_not_all_zero() -> None:
    with pytest.raises(ValueError):
        EdgeSettings(staff_w_standing=-0.1, _env_file=None)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        EdgeSettings(staff_w_appearance=0, staff_w_standing=0, staff_w_behaviour=0, _env_file=None)  # type: ignore[call-arg]


def test_appearance_high_must_exceed_low() -> None:
    with pytest.raises(ValueError):
        EdgeSettings(appearance_low=0.8, appearance_high=0.8, _env_file=None)  # type: ignore[call-arg]


def test_build_vision_passes_rotation_to_the_capture_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    class Capture:
        @staticmethod
        def Cv2Source(source: str, fps: float, *, rotate: int) -> object:
            seen["rotate"] = rotate
            return object()

    class Yolo:
        @staticmethod
        def YoloDetector(model: str, *, fps: float) -> object:
            seen["detector_fps"] = fps
            return object()

    modules = {"capture": Capture, "yolo": Yolo}
    monkeypatch.setattr(app, "_adapter", lambda name: modules[name])
    settings = EdgeSettings(
        source="http://phone/video",
        rotate=90,
        target_fps=6.0,
        pose_model="",
        blur=False,
        _env_file=None,
    )  # type: ignore[call-arg]
    app.build_vision(settings)
    # The tracker sizes its lost-track buffer in seconds, so it must know the real frame rate.
    assert seen == {"rotate": 90, "detector_fps": 6.0}


def test_build_vision_subscribes_to_cloud_frames_as_this_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    class Frames:
        @staticmethod
        def open_frames_source(source: str, **kw: Any) -> object:
            seen.update(kw, source=source)
            return object()

    class Yolo:
        @staticmethod
        def YoloDetector(model: str, *, fps: float) -> object:
            return object()

    modules = {"capture": object(), "mqtt_frames": Frames, "yolo": Yolo}
    monkeypatch.setattr(app, "_adapter", lambda name: modules[name])
    settings = EdgeSettings(
        source="mqtt-frames://cam-coleg-1",
        mqtt_edge_user="vision-01",
        site="demo",
        pose_model="",
        blur=False,
        _env_file=None,
    )  # type: ignore[call-arg]
    app.build_vision(settings)
    assert seen["source"] == "mqtt-frames://cam-coleg-1"
    assert (seen["user"], seen["device"], seen["site"]) == ("vision-01", "vision-01", "demo")


def test_missing_vision_adapter_gives_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    real = importlib.import_module

    def fake_import(name: str, package: str | None = None) -> Any:
        if name == "aivee_edge.adapters.yolo":
            raise ImportError("No module named 'ultralytics'")
        return real(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    with pytest.raises(app.VisionUnavailable, match=r"adapters\.yolo .*fake_edge"):
        app.build_vision(EdgeSettings(source="0", _env_file=None))  # type: ignore[call-arg]


def test_run_exits_with_code_2_when_vision_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_s: EdgeSettings) -> app.Vision:
        raise app.VisionUnavailable("no models")

    monkeypatch.setattr(app, "build_vision", boom)
    assert app.run(EdgeSettings(_env_file=None)) == 2  # type: ignore[call-arg]


def test_crop_embedder_crops_the_normalised_box() -> None:
    seen: list[tuple[int, ...]] = []

    class Inner:
        def embed(self, crop: Any) -> list[float]:
            seen.append(crop.shape)
            return [1.0]

    image = np.zeros((100, 200, 3), dtype=np.uint8)
    emb = app.CropEmbedder(Inner())
    assert emb.embed(image, (0.1, 0.2, 0.6, 0.7)) == [1.0]
    assert seen == [(50, 100, 3)]
    assert emb.embed(image, (0.5, 0.5, 0.5, 0.5)) is None  # empty crop


def test_snapshot_failure_does_not_block_the_alert() -> None:
    class Broken:
        def blur(self, image: Any) -> Any:
            raise RuntimeError("yunet")

    assert app.BlurredJpeg(Broken(), lambda img: b"x").make(np.zeros((2, 2, 3))) is None

    class Ok:
        def blur(self, image: Any) -> Any:
            return image

    assert app.BlurredJpeg(Ok(), lambda img: b"jpeg").make(np.zeros((2, 2, 3))) == b"jpeg"


def test_crop_blurs_the_whole_frame_then_cuts_the_padded_person_box() -> None:
    blurred: list[tuple[int, ...]] = []
    encoded: list[tuple[int, ...]] = []

    class Ok:
        def blur(self, image: Any) -> Any:
            blurred.append(image.shape)
            return image

    def encode(img: Any) -> bytes:
        encoded.append(img.shape)
        return b"crop"

    snaps = app.BlurredJpeg(Ok(), encode)
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    assert snaps.crop(image, (0.25, 0.2, 0.75, 0.8)) == b"crop"
    assert blurred == [(100, 200, 3)]  # faces are found with the full frame as context
    assert encoded == [(72, 120, 3)]  # 10% padding on every side
    assert snaps.crop(image, (0.5, 0.5, 0.5, 0.5)) is None  # empty box


def test_crop_failure_gives_none() -> None:
    class Broken:
        def blur(self, image: Any) -> Any:
            raise RuntimeError("yunet")

    snaps = app.BlurredJpeg(Broken(), lambda img: b"x")
    assert snaps.crop(np.zeros((10, 10, 3)), (0, 0, 1, 1)) is None


class _EndedSource:
    def read(self) -> None:
        return None


class _QuietClient:
    """Stands in for MqttEdgeClient: no broker, no rules, no commands."""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def rules(self) -> list[Any]:
        return []

    def camera(self) -> Any:
        raise LookupError

    def profiles(self) -> None:
        return None

    def take_commands(self) -> list[Any]:
        return []


def test_run_logs_the_source_without_its_password(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    vision = app.Vision(_EndedSource(), object(), None, None, None)  # type: ignore[arg-type]
    monkeypatch.setattr(app, "build_vision", lambda _s: vision)
    monkeypatch.setattr(app, "build_client", lambda _s: _QuietClient())
    settings = EdgeSettings(source="rtsp://admin:s3cr3t@10.0.0.5:554/stream2", _env_file=None)  # type: ignore[call-arg]
    with caplog.at_level("INFO"):
        assert app.run(settings) == 0
    assert "s3cr3t" not in caplog.text
    assert "source=rtsp://admin:***@10.0.0.5:554/stream2" in caplog.text


class _Frames:
    """A camera that gives `n` frames, then ends."""

    def __init__(self, n: int) -> None:
        self.left = n
        self.closed = False

    def read(self) -> tuple[float, Any] | None:
        if self.left == 0:
            return None
        self.left -= 1
        return float(10 - self.left), np.zeros((4, 4, 3), np.uint8)

    def close(self) -> None:
        self.closed = True


class _NoPeople:
    def detect(self, _image: Any, ts: float) -> Any:
        from aivee_edge.domain.observation import Frame

        return Frame(ts)


def test_cameras_run_in_one_process_on_one_mqtt_client(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from aivee_contracts.events import DeviceStatus
    from aivee_edge.adapters.mqtt import MqttEdgeClient

    for name in ("SOURCE", "CLIP_EPOCH", "PROGRESS_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(
        "CAMERAS",
        "cam-01=rtsp://admin:s3cr3t@10.0.0.21/stream2;cam-02=rtsp://admin:s3cr3t@10.0.0.22/stream2",
    )
    built: list[tuple[str, str]] = []
    sources: list[_Frames] = []

    def fake_vision(s: EdgeSettings) -> app.Vision:
        built.append((s.camera_id, s.source))
        sources.append(_Frames(3))
        return app.Vision(sources[-1], _NoPeople(), None, None, None)

    clients: list[MqttEdgeClient] = []
    real_client = app.build_client

    def fake_client(s: EdgeSettings) -> MqttEdgeClient:
        client = real_client(s)
        client.start = lambda timeout=10.0: None  # type: ignore[method-assign]
        client.stop = lambda: None  # type: ignore[method-assign]
        clients.append(client)
        return client

    monkeypatch.setattr(app, "build_vision", fake_vision)
    monkeypatch.setattr(app, "build_client", fake_client)
    settings = EdgeSettings(_env_file=None, pose_model="", blur=False)  # type: ignore[call-arg]
    with caplog.at_level("INFO"):
        assert app.run(settings) == 0
    assert built == [
        ("cam-01", "rtsp://admin:s3cr3t@10.0.0.21/stream2"),
        ("cam-02", "rtsp://admin:s3cr3t@10.0.0.22/stream2"),
    ]
    assert all(src.left == 0 and src.closed for src in sources)  # every camera ran to its end
    [client] = clients
    status = DeviceStatus.model_validate_json(client._status("online"))
    assert status.cameras == ["cam-01", "cam-02"]
    assert "s3cr3t" not in caplog.text
    assert "camera=cam-02 source=rtsp://admin:***@10.0.0.22/stream2" in caplog.text


def test_a_source_next_to_cameras_says_cameras_are_ignored(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    vision = app.Vision(_EndedSource(), object(), None, None, None)  # type: ignore[arg-type]
    monkeypatch.setattr(app, "build_vision", lambda _s: vision)
    monkeypatch.setattr(app, "build_client", lambda _s: _QuietClient())
    monkeypatch.setenv("CAMERAS", "cam-01=rtsp://a/1;cam-02=rtsp://a/2")
    settings = EdgeSettings(source="rtsp://mediamtx:8554/cam-01", _env_file=None)  # type: ignore[call-arg]
    with caplog.at_level("INFO"):
        assert app.run(settings) == 0
    assert "CAMERAS ignored" in caplog.text


class _LiveCamera(_Frames):
    """A live camera (it has `health()`) that keeps giving frames until `enough()` says so."""

    def __init__(self, enough: Any) -> None:
        super().__init__(10_000)
        self.enough = enough

    def read(self) -> tuple[float, Any] | None:
        import time

        time.sleep(0.002)
        return None if self.enough() else super().read()

    def health(self) -> Any:
        from aivee_edge.domain.camera_health import SourceHealth

        return SourceHealth(True, 0.05, 15.0, 4, 4)


def _offline_client(clients: list[Any]) -> Any:
    real_client = app.build_client

    def fake_client(s: EdgeSettings) -> Any:
        client = real_client(s)
        client.start = lambda timeout=10.0: None
        client.stop = lambda: None
        clients.append(client)
        return client

    return fake_client


def _published_health(clients: list[Any]) -> list[Any]:
    from aivee_contracts.events import DeviceStatus

    return DeviceStatus.model_validate_json(clients[0]._status("online")).camera_health


def test_a_single_live_camera_puts_its_health_on_the_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    for name in ("CAMERAS", "CLIP_EPOCH", "PROGRESS_FILE"):
        monkeypatch.delenv(name, raising=False)
    clients: list[Any] = []
    deadline = time.monotonic() + 5
    source = _LiveCamera(
        lambda: bool(clients and _published_health(clients)) or time.monotonic() > deadline
    )
    vision = app.Vision(source, _NoPeople(), None, None, None)
    monkeypatch.setattr(app, "build_vision", lambda _s: vision)
    monkeypatch.setattr(app, "build_client", _offline_client(clients))
    monkeypatch.setattr(app, "HEALTH_TICK_S", 0.01)
    settings = EdgeSettings(
        source="rtsp://cam/1", camera_id="cam-01", _env_file=None, pose_model="", blur=False
    )  # type: ignore[call-arg]
    assert app.run(settings) == 0
    assert [(h.camera_id, h.state) for h in _published_health(clients)] == [("cam-01", "ok")]


def test_cameras_put_their_health_on_the_status(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    for name in ("SOURCE", "CLIP_EPOCH", "PROGRESS_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CAMERAS", "cam-01=rtsp://a/1;cam-02=rtsp://a/2")
    clients: list[Any] = []
    deadline = time.monotonic() + 5

    def enough() -> bool:
        return bool(clients and len(_published_health(clients)) == 2) or time.monotonic() > deadline

    monkeypatch.setattr(
        app,
        "build_vision",
        lambda _s: app.Vision(_LiveCamera(enough), _NoPeople(), None, None, None),
    )
    monkeypatch.setattr(app, "build_client", _offline_client(clients))
    monkeypatch.setattr(app, "HEALTH_TICK_S", 0.01)
    settings = EdgeSettings(_env_file=None, pose_model="", blur=False)  # type: ignore[call-arg]
    assert app.run(settings) == 0
    assert [h.camera_id for h in _published_health(clients)] == ["cam-01", "cam-02"]
