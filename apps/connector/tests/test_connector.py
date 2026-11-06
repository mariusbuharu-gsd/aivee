"""Unit tests for the cloud-mode stream connector (pure argument building, no ffmpeg run)."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_PATH = Path(__file__).resolve().parents[1] / "connector.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("aivee_connector", _PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["aivee_connector"] = module
    spec.loader.exec_module(module)
    return module


c = _load()


def cfg(**kw: object) -> object:
    base: dict[str, object] = {
        "source": "rtsp://192.168.1.20:554/stream1",
        "camera_id": "cam-01",
        "url": "rtsp://cloud.example:8554",
        "user": "pub",
        "password": "s3cret",
    }
    base.update(kw)
    return c.Config(**base)


def test_publish_url_carries_encoded_credentials_and_camera_path() -> None:
    url = c.publish_url(cfg(user="pub@x", password="p:a/ss w"))
    assert url == "rtsp://pub%40x:p%3Aa%2Fss%20w@cloud.example:8554/cam-01"


def test_publish_url_without_credentials() -> None:
    assert c.publish_url(cfg(user="", password="")) == "rtsp://cloud.example:8554/cam-01"


def test_rtsp_source_uses_tcp_and_small_h264_output() -> None:
    args = c.ffmpeg_args(cfg())
    assert args[0] == "ffmpeg"
    i = args.index("-i")
    assert args[i - 2 : i] == ["-rtsp_transport", "tcp"]
    assert args[i + 1] == "rtsp://192.168.1.20:554/stream1"
    vf = args[args.index("-vf") + 1]
    assert vf == "fps=5,scale=640:-2"
    assert args[args.index("-c:v") + 1] == "libx264"
    assert "-an" in args
    assert args[-1].endswith("@cloud.example:8554/cam-01")


def test_mjpeg_phone_source_gets_wallclock_timestamps_and_rotation() -> None:
    args = c.ffmpeg_args(cfg(source="http://192.168.1.30:8080/video", rotate=90))
    i = args.index("-i")
    assert "-use_wallclock_as_timestamps" in args[:i]
    assert "-rtsp_transport" not in args[:i]
    assert args[args.index("-vf") + 1] == "fps=5,transpose=1,scale=640:-2"


@pytest.mark.parametrize(
    ("degrees", "chain"),
    [(0, ""), (90, "transpose=1,"), (180, "transpose=1,transpose=1,"), (270, "transpose=2,")],
)
def test_rotation_filters(degrees: int, chain: str) -> None:
    args = c.ffmpeg_args(cfg(rotate=degrees, fps=3, width=480))
    assert args[args.index("-vf") + 1] == f"fps=3,{chain}scale=480:-2"


def test_file_source_loops_in_real_time() -> None:
    args = c.ffmpeg_args(cfg(source="recordings/sala-1.mp4"))
    i = args.index("-i")
    assert args[1:i] == ["-hide_banner", "-loglevel", "warning", "-re", "-stream_loop", "-1"]


def test_bitrate_caps_the_stream() -> None:
    args = c.ffmpeg_args(cfg(bitrate_kbps=300))
    assert args[args.index("-b:v") + 1] == "300k"
    assert args[args.index("-maxrate") + 1] == "300k"
    assert args[args.index("-bufsize") + 1] == "600k"


def test_redact_hides_the_password() -> None:
    args = c.ffmpeg_args(cfg(password="s3cret"))
    shown = " ".join(c.redact(args, "s3cret"))
    assert "s3cret" not in shown
    assert "***" in shown


@pytest.mark.parametrize("bad", ["", "cam 01", "../x", "cam/01"])
def test_camera_id_must_be_a_safe_path(bad: str) -> None:
    with pytest.raises(ValueError):
        cfg(camera_id=bad)


def test_rotation_must_be_a_right_angle() -> None:
    with pytest.raises(ValueError):
        cfg(rotate=45)


def test_from_env_reads_names_and_defaults() -> None:
    conf = c.Config.from_env(
        {
            "SOURCE": "0",
            "CAMERA_ID": "cam-02",
            "CLOUD_RTSP_URL": "rtsp://h:8554",
            "STREAM_PUBLISH_USER": "u",
            "STREAM_PUBLISH_PASSWORD": "p",
        }
    )
    assert (conf.camera_id, conf.fps, conf.width, conf.rotate, conf.bitrate_kbps) == (
        "cam-02",
        5,
        640,
        0,
        400,
    )


def test_backoff_grows_and_resets_after_a_long_run() -> None:
    b = c.Backoff(start_s=1, max_s=8, healthy_after_s=60)
    assert [b.next_delay(ran_s=1) for _ in range(5)] == [1, 2, 4, 8, 8]
    assert b.next_delay(ran_s=120) == 1


def test_redact_touches_only_the_url_credentials() -> None:
    args = c.ffmpeg_args(cfg(user="u", password="p"))
    shown = c.redact(args, "p")
    assert shown[0] == "ffmpeg"
    assert "-pix_fmt" in shown
    assert shown[-1] == "rtsp://u:***@cloud.example:8554/cam-01"
