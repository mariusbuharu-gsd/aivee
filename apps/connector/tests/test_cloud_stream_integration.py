"""MediaMTX with the real `infra/mediamtx` config: publishing needs the publish credentials,
reading stays open (live view and the cloud vision worker)."""

import secrets
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

INFRA = Path(__file__).resolve().parents[3] / "infra" / "mediamtx"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg on the host"),
]


@dataclass(frozen=True)
class Mtx:
    base: str
    user: str
    password: str


@pytest.fixture(scope="module")
def mtx() -> Iterator[Mtx]:
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.wait_strategies import LogMessageWaitStrategy

    user, password = "publisher", secrets.token_hex(16)
    container = (
        DockerContainer("bluenviron/mediamtx:1-ffmpeg")
        .with_volume_mapping(str(INFRA / "mediamtx.yml"), "/mediamtx.base.yml")
        .with_volume_mapping(str(INFRA / "entrypoint.sh"), "/entrypoint.sh")
        .with_kwargs(entrypoint=["/bin/sh", "/entrypoint.sh"])
        .with_envs(STREAM_PUBLISH_USER=user, STREAM_PUBLISH_PASSWORD=password)
        .with_exposed_ports(8554)
        .waiting_for(LogMessageWaitStrategy(r"\[RTSP\] started").with_startup_timeout(30))
    )
    with container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(8554)
        yield Mtx(base=f"rtsp://{host}:{port}", user=user, password=password)


def _publish(url: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-re",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=5", "-t", "8",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-f", "rtsp", "-rtsp_transport", "tcp", url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )  # fmt: skip


def _url(mtx: Mtx, path: str, user: str = "", password: str = "") -> str:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "aivee_connector_it", Path(__file__).resolve().parents[1] / "connector.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(mod)
    cfg = mod.Config(source="x.mp4", camera_id=path, url=mtx.base, user=user, password=password)
    return str(mod.publish_url(cfg))


def _readable(url: str) -> bool:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-rtsp_transport", "tcp", "-show_streams", url],
        capture_output=True,
        timeout=15,
    )
    return probe.returncode == 0 and b"codec_name=h264" in probe.stdout


def test_publish_without_credentials_is_refused(mtx: Mtx) -> None:
    proc = _publish(_url(mtx, "cam-anon"))
    assert proc.wait(timeout=20) != 0


def test_publish_with_wrong_password_is_refused(mtx: Mtx) -> None:
    proc = _publish(_url(mtx, "cam-wrong", mtx.user, "nope"))
    assert proc.wait(timeout=20) != 0


def test_publish_with_credentials_is_readable_without_them(mtx: Mtx) -> None:
    proc = _publish(_url(mtx, "cam-ok", mtx.user, mtx.password))
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not _readable(f"{mtx.base}/cam-ok"):
            time.sleep(0.5)
        assert _readable(f"{mtx.base}/cam-ok")
    finally:
        proc.terminate()
        proc.wait(timeout=10)
