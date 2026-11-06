"""Unit tests for the cloud-mode stream connector (pure argument building, no ffmpeg run)."""

import base64
import importlib.util
import io
import sys
import threading
import time
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


# --- frames over HTTPS (--push) -------------------------------------------------------------

JPEG_A = b"\xff\xd8\xff\xe0AAAA\xff\x00\xffBB\xff\xd9"
JPEG_B = b"\xff\xd8\xff\xdbCC\xff\xd9"


def push_cfg(**kw: object) -> object:
    return cfg(push_url="https://app.example", source="0", **kw)


def test_webcam_index_uses_v4l2_on_linux_and_avfoundation_on_macos() -> None:
    linux = c.frames_ffmpeg_args(push_cfg(), platform="linux")
    i = linux.index("-i")
    assert linux[i - 2 : i + 2] == ["-f", "v4l2", "-i", "/dev/video0"]
    mac = c.frames_ffmpeg_args(push_cfg(), platform="darwin")
    i = mac.index("-i")
    assert mac[i - 4 : i + 2] == ["-f", "avfoundation", "-framerate", "30", "-i", "0"]
    rtsp = c.ffmpeg_args(cfg(source="0"), platform="linux")  # the RTSP path is unchanged
    i = rtsp.index("-i")
    assert rtsp[i - 2 : i + 2] == ["-f", "v4l2", "-i", "/dev/video0"]


def test_frames_args_emit_rotated_small_jpegs_on_stdout() -> None:
    args = c.frames_ffmpeg_args(push_cfg(rotate=90, width=640, fps=5, jpeg_quality=6))
    assert args[args.index("-vf") + 1] == "fps=5,transpose=1,scale=640:-2"
    assert args[args.index("-c:v") + 1] == "mjpeg"
    assert args[args.index("-q:v") + 1] == "6"
    assert args[-3:] == ["-f", "image2pipe", "pipe:1"]
    assert "s3cret" not in " ".join(args)


def test_push_config_from_env_and_validation() -> None:
    conf = c.Config.from_env(
        {"SOURCE": "0", "CLOUD_PUSH_URL": "https://h", "CLOUD_JPEG_QUALITY": "8"}
    )
    assert (conf.push_url, conf.jpeg_quality) == ("https://h", 8)
    with pytest.raises(ValueError):
        push_cfg(jpeg_quality=1)
    with pytest.raises(ValueError):
        cfg(push_url="ftp://h")


def test_splitter_cuts_jpegs_across_chunk_boundaries_and_skips_garbage() -> None:
    stream = b"junk" + JPEG_A + JPEG_B + JPEG_A[:5]
    s = c.JpegSplitter()
    out: list[bytes] = []
    for i in range(0, len(stream), 3):  # tiny chunks split the markers themselves
        out += s.feed(stream[i : i + 3])
    assert out == [JPEG_A, JPEG_B]
    assert s.feed(JPEG_A[5:]) == [JPEG_A]


def test_splitter_drops_an_endless_frame() -> None:
    s = c.JpegSplitter(max_bytes=10)
    assert s.feed(b"\xff\xd8" + b"x" * 20) == []
    assert s.feed(JPEG_B) == [JPEG_B]


def test_iter_jpegs_reads_a_pipe() -> None:
    stream = io.BufferedReader(io.BytesIO(JPEG_A + JPEG_B))  # type: ignore[arg-type]
    assert list(c.iter_jpegs(stream)) == [JPEG_A, JPEG_B]


def test_frame_request_has_path_and_basic_auth() -> None:
    path, headers = c.frame_request(push_cfg(user="pub", password="p:w"))
    assert path == "/api/ingest/frames/cam-01"
    assert headers["Authorization"] == "Basic " + base64.b64encode(b"pub:p:w").decode()
    assert headers["Content-Type"] == "image/jpeg"
    path, _ = c.frame_request(cfg(push_url="https://h.example/aivee/", source="0"))
    assert path == "/aivee/api/ingest/frames/cam-01"


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def read(self) -> bytes:
        return b""


class FakeConn:
    def __init__(self, statuses: list[object]) -> None:
        self.statuses = statuses
        self.requests: list[tuple[str, str, bytes]] = []
        self.closed = False
        self._status = 0

    def request(self, method: str, url: str, body: bytes, headers: object) -> None:
        self.requests.append((method, url, body))
        nxt = self.statuses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        assert isinstance(nxt, int)
        self._status = nxt

    def getresponse(self) -> FakeResponse:
        return FakeResponse(self._status)

    def close(self) -> None:
        self.closed = True


def test_pusher_reuses_one_connection_and_backs_off_on_errors() -> None:
    conns: list[FakeConn] = []
    statuses: list[object] = [204, 204, 503, ConnectionResetError("reset"), 204]

    def connect(url: str) -> FakeConn:
        conn = FakeConn(statuses)
        conns.append(conn)
        return conn

    sleeps: list[float] = []
    p = c.FramePusher(push_cfg(), connect, sleep=sleeps.append)
    results = [p.send(JPEG_A) for _ in range(5)]
    assert results == [True, True, False, False, True]
    assert sleeps == [1.0, 2.0]  # backoff grows; a success resets it
    assert len(conns) == 2 and conns[0].closed  # reconnect only after the connection broke
    assert conns[0].requests[0] == ("POST", "/api/ingest/frames/cam-01", JPEG_A)
    assert p.sent == 3


def test_newest_slot_keeps_only_the_latest_frame() -> None:
    slot = c.Newest()
    for frame in (b"1", b"2", b"3"):
        slot.put(frame)
    assert slot.take(0) == b"3"
    assert slot.dropped == 2
    assert slot.take(0.01) is None


def test_slow_server_drops_frames_instead_of_queueing() -> None:
    gate = threading.Event()
    sent: list[bytes] = []

    class SlowConn(FakeConn):
        def request(self, method: str, url: str, body: bytes, headers: object) -> None:
            gate.wait(2)  # the server holds the first request
            sent.append(body)
            self._status = 204

    slot, stop = c.Newest(), threading.Event()
    p = c.FramePusher(push_cfg(), lambda url: SlowConn([]))
    t = threading.Thread(target=p.run, args=(slot, stop))
    t.start()
    slot.put(b"f0")
    time.sleep(0.05)  # the sender took f0 and is stuck on it
    for i in range(1, 10):
        slot.put(f"f{i}".encode())
    gate.set()
    time.sleep(0.1)
    stop.set()
    t.join(3)
    assert sent == [b"f0", b"f9"]
    assert slot.dropped == 8
