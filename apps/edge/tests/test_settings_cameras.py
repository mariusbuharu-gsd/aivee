"""CAMERAS: several cameras on one edge device, next to the single-camera SOURCE/CAMERA_ID."""

import pytest
from aivee_edge.__main__ import parse
from aivee_edge.settings import CameraSpec, EdgeSettings, parse_cameras

TWO = "cam-01=rtsp://admin:s3cr3t@192.168.1.21:554/stream2;cam-02=rtsp://admin:s3cr3t@192.168.1.22:554/stream2"


@pytest.fixture(autouse=True)
def _no_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    # The repo's .env must not leak into these tests.
    monkeypatch.setitem(EdgeSettings.model_config, "env_file", None)
    for name in ("CAMERAS", "SOURCE", "CAMERA_ID", "CLIP_EPOCH", "PROGRESS_FILE", "EDGE_JOBS"):
        monkeypatch.delenv(name, raising=False)


def test_parse_cameras_reads_id_url_pairs() -> None:
    assert parse_cameras(TWO) == [
        CameraSpec("cam-01", "rtsp://admin:s3cr3t@192.168.1.21:554/stream2"),
        CameraSpec("cam-02", "rtsp://admin:s3cr3t@192.168.1.22:554/stream2"),
    ]


def test_parse_cameras_accepts_newlines_spaces_and_a_trailing_separator() -> None:
    text = "\n  cam-01 = rtsp://h1/stream2 ;\n cam-02=rtsp://h2/stream2?x=1&y=2;\n"
    assert parse_cameras(text) == [
        CameraSpec("cam-01", "rtsp://h1/stream2"),
        CameraSpec("cam-02", "rtsp://h2/stream2?x=1&y=2"),
    ]
    assert parse_cameras("") == []


@pytest.mark.parametrize(
    "text",
    [
        "rtsp://admin:s3cr3t@h/stream2",  # no id
        "cam 01=rtsp://admin:s3cr3t@h/stream2",  # not an API camera id
        "cam-01=",  # no url
        "cam-01=rtsp://admin:s3cr3t@h1/a;cam-01=rtsp://admin:s3cr3t@h2/b",  # duplicate id
    ],
)
def test_parse_cameras_rejects_bad_entries_without_leaking_the_password(text: str) -> None:
    with pytest.raises(ValueError) as e:
        parse_cameras(text)
    assert "s3cr3t" not in str(e.value)


def test_cameras_env_runs_every_camera(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMERAS", TWO)
    s = EdgeSettings()
    assert s.multi_camera
    assert [c.id for c in s.camera_specs()] == ["cam-01", "cam-02"]


def test_without_cameras_the_single_camera_settings_are_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOURCE", "rtsp://cam/stream2")
    monkeypatch.setenv("CAMERA_ID", "cam-07")
    s = EdgeSettings()
    assert not s.multi_camera
    assert s.camera_specs() == [CameraSpec("cam-07", "rtsp://cam/stream2")]


def test_an_explicit_source_wins_over_cameras(monkeypatch: pytest.MonkeyPatch) -> None:
    # The cloud vision service, `make edge SOURCE=…` and the API's clip runs all set SOURCE
    # (or --source); a CAMERAS line in the shared .env must not hijack them.
    monkeypatch.setenv("CAMERAS", TWO)
    monkeypatch.setenv("SOURCE", "rtsp://mediamtx:8554/cam-coleg-1")
    assert not EdgeSettings().multi_camera
    monkeypatch.delenv("SOURCE")
    s = parse(["--source", "clip.mp4", "--clip-epoch", "2026-11-23T10:00:00Z"])
    assert not s.multi_camera
    assert s.camera_specs() == [CameraSpec("cam-01", "clip.mp4")]


def test_cameras_cannot_run_an_offline_clip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMERAS", TWO)
    monkeypatch.setenv("CLIP_EPOCH", "2026-11-23T10:00:00Z")
    with pytest.raises(ValueError, match="CAMERAS"):
        EdgeSettings()


def test_bad_cameras_env_fails_at_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMERAS", "cam-01=rtsp://a/1;cam-01=rtsp://a/2")
    with pytest.raises(ValueError, match="cam-01"):
        EdgeSettings()


def test_a_bad_cameras_env_error_does_not_echo_the_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMERAS", "cam-01=rtsp://admin:s3cr3t@h/a;cam-01=rtsp://admin:s3cr3t@h/b")
    with pytest.raises(ValueError) as e:
        EdgeSettings()
    assert "s3cr3t" not in str(e.value)


# -- edge box: neither SOURCE nor CAMERAS, the cameras come from the dashboard ----------------


def test_the_three_camera_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    assert EdgeSettings().camera_mode == "box"
    monkeypatch.setenv("CAMERAS", TWO)
    assert EdgeSettings().camera_mode == "cameras"
    monkeypatch.setenv("SOURCE", "rtsp://cam/stream2")
    assert EdgeSettings().camera_mode == "single"
    monkeypatch.delenv("CAMERAS")
    assert EdgeSettings().camera_mode == "single"


def test_a_box_cannot_run_an_offline_clip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIP_EPOCH", "2026-11-23T10:00:00Z")
    with pytest.raises(ValueError, match="SOURCE"):
        EdgeSettings()


def test_jobs_run_on_a_box_and_with_cameras_unless_turned_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert EdgeSettings().serves_jobs
    monkeypatch.setenv("CAMERAS", TWO)
    assert EdgeSettings().serves_jobs
    monkeypatch.setenv("EDGE_JOBS", "false")
    assert not EdgeSettings().serves_jobs


def test_a_single_source_serves_jobs_only_when_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    # The cloud vision workers run with SOURCE=mqtt-frames://…: they must not scan the server.
    monkeypatch.setenv("SOURCE", "mqtt-frames://cam-coleg-1")
    assert not EdgeSettings().serves_jobs
    monkeypatch.setenv("SOURCE", "0")
    monkeypatch.setenv("EDGE_JOBS", "true")
    assert EdgeSettings().serves_jobs
    monkeypatch.setenv("SOURCE", "clip.mp4")
    monkeypatch.setenv("CLIP_EPOCH", "2026-11-23T10:00:00Z")
    assert not EdgeSettings().serves_jobs  # an offline clip run never does
