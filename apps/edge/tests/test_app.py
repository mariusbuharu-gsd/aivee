"""Entry point wiring without cameras, models or a broker."""

import importlib
from typing import Any

import numpy as np
import pytest
from aivee_edge import app
from aivee_edge.__main__ import parse
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
        def YoloDetector(model: str) -> object:
            return object()

    modules = {"capture": Capture, "yolo": Yolo}
    monkeypatch.setattr(app, "_adapter", lambda name: modules[name])
    settings = EdgeSettings(
        source="http://phone/video", rotate=90, pose_model="", blur=False, _env_file=None
    )  # type: ignore[call-arg]
    app.build_vision(settings)
    assert seen == {"rotate": 90}


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
