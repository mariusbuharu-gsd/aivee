"""AiVee stream connector (cloud mode, restaurant side).

Pulls one camera on the restaurant network (RTSP, phone MJPEG, webcam index or a video file)
and sends it to the AiVee cloud. It does no analysis and stores nothing: the cloud vision
worker analyses the frames in memory. Two ways out:

- RTSP (default): a small H.264 stream into MediaMTX (`--url`, CLOUD_RTSP_URL).
- HTTPS (`--push https://HOST`, CLOUD_PUSH_URL): JPEG frames POSTed one by one to
  `/api/ingest/frames/{camera_id}` over a keep-alive connection, for networks where only 443
  is open. A slow server makes the connector drop frames, never queue them.

Both authenticate with STREAM_PUBLISH_USER/PASSWORD (one shared credential for now; per-device
keys replace it after the freeze).

Standard library only, so it runs on any PC or small box that has Python 3 and ffmpeg.

    python3 connector.py --source http://PHONE:8080/video --camera-id cam-01 --rotate 90
    python3 connector.py --source 0 --camera-id cam-coleg-1 --push https://app.example

Env: SOURCE, CAMERA_ID, CLOUD_RTSP_URL, CLOUD_PUSH_URL, STREAM_PUBLISH_USER,
STREAM_PUBLISH_PASSWORD, CLOUD_FPS, CLOUD_WIDTH, CLOUD_BITRATE_KBPS, CLOUD_JPEG_QUALITY, ROTATE.
Flags override env.
"""

from __future__ import annotations

import argparse
import base64
import http.client
import logging
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import IO, Protocol
from urllib.parse import quote, urlsplit, urlunsplit

log = logging.getLogger("aivee.connector")

_CAMERA_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_TRANSPOSE = {0: "", 90: "transpose=1,", 180: "transpose=1,transpose=1,", 270: "transpose=2,"}


@dataclass(frozen=True)
class Config:
    source: str
    camera_id: str
    url: str = "rtsp://localhost:8554"
    """Base RTSP(S) URL of the AiVee cloud MediaMTX, without the camera path."""
    user: str = ""
    password: str = field(default="", repr=False)
    fps: int = 5
    width: int = 640
    rotate: int = 0
    """Clockwise rotation applied before upload, so the cloud and live view see it upright."""
    bitrate_kbps: int = 400
    push_url: str = ""
    """HTTPS base URL of the AiVee API; set = frames over HTTPS instead of RTSP."""
    jpeg_quality: int = 6
    """ffmpeg `-q:v` for the HTTPS frames: 2 (best, biggest) to 31 (worst)."""

    def __post_init__(self) -> None:
        if not _CAMERA_ID.match(self.camera_id):
            raise ValueError("CAMERA_ID may contain only letters, digits, '-' and '_'")
        if self.rotate not in _TRANSPOSE:
            raise ValueError(f"ROTATE must be one of {sorted(_TRANSPOSE)}")
        if not self.source:
            raise ValueError("SOURCE is required")
        if self.fps < 1 or self.width < 160 or self.bitrate_kbps < 50:
            raise ValueError("fps >= 1, width >= 160 and bitrate >= 50 kbps")
        if not 2 <= self.jpeg_quality <= 31:
            raise ValueError("CLOUD_JPEG_QUALITY must be 2..31")
        if self.push_url and urlsplit(self.push_url).scheme not in ("http", "https"):
            raise ValueError("--push needs an https:// URL (http:// only for local tests)")

    @classmethod
    def from_env(cls, env: Mapping[str, str], **overrides: object) -> Config:
        values: dict[str, object] = {
            "source": env.get("SOURCE", ""),
            "camera_id": env.get("CAMERA_ID", "cam-01"),
            "url": env.get("CLOUD_RTSP_URL") or "rtsp://localhost:8554",
            "user": env.get("STREAM_PUBLISH_USER", ""),
            "password": env.get("STREAM_PUBLISH_PASSWORD", ""),
            "fps": int(env.get("CLOUD_FPS") or 5),
            "width": int(env.get("CLOUD_WIDTH") or 640),
            "rotate": int(env.get("ROTATE") or 0),
            "bitrate_kbps": int(env.get("CLOUD_BITRATE_KBPS") or 400),
            "push_url": env.get("CLOUD_PUSH_URL", ""),
            "jpeg_quality": int(env.get("CLOUD_JPEG_QUALITY") or 6),
        }
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)  # type: ignore[arg-type]


def publish_url(cfg: Config) -> str:
    """The MediaMTX path for this camera, with URL-encoded credentials when set."""
    parts = urlsplit(cfg.url.rstrip("/"))
    netloc = parts.netloc.rsplit("@", 1)[-1]
    if cfg.user:
        netloc = f"{quote(cfg.user, safe='')}:{quote(cfg.password, safe='')}@{netloc}"
    path = f"{parts.path}/{cfg.camera_id}"
    return urlunsplit((parts.scheme, netloc, path, "", ""))


def _input_args(source: str, platform: str = sys.platform) -> list[str]:
    if source.startswith(("rtsp://", "rtsps://")):
        return ["-rtsp_transport", "tcp"]
    if source.startswith(("http://", "https://")):
        # Phone MJPEG streams carry no timestamps.
        return ["-use_wallclock_as_timestamps", "1"]
    if source.isdigit() or source.startswith("video="):
        if platform == "darwin":
            return ["-f", "avfoundation", "-framerate", "30"]
        if platform.startswith("win"):
            return ["-f", "dshow"]
        return ["-f", "v4l2"]
    return ["-re", "-stream_loop", "-1"]  # a recorded file, replayed in real time


_DSHOW_VIDEO = re.compile(r'"([^"]+)"\s*\(video\)')
_DSHOW_LEGACY_SECTION = re.compile(r"DirectShow (video|audio) devices")
_DSHOW_LEGACY_NAME = re.compile(r'\]\s+"([^"]+)"\s*$')


def parse_dshow_devices(stderr: str) -> list[str]:
    """Video device names from `ffmpeg -list_devices true -f dshow -i dummy`. Newer ffmpeg
    tags each line `"Name" (video)`; older builds list names under a "DirectShow video
    devices" heading instead."""
    names = _DSHOW_VIDEO.findall(stderr)
    if names:
        return names
    section, legacy = "", []
    for line in stderr.splitlines():
        if heading := _DSHOW_LEGACY_SECTION.search(line):
            section = heading.group(1)
        elif section == "video" and (name := _DSHOW_LEGACY_NAME.search(line)):
            legacy.append(name.group(1))
    return legacy


def dshow_device(index: int) -> str:
    """The Windows webcam number `index` (0 = first), as ffmpeg's `video=<name>`."""
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
        capture_output=True,
        text=True,
        check=False,
    )
    names = parse_dshow_devices(out.stderr)
    if index >= len(names):
        found = ", ".join(names) or "none"
        raise SystemExit(f"webcam {index} not found (DirectShow video devices: {found})")
    return f"video={names[index]}"


def _input(cfg: Config, platform: str = sys.platform) -> list[str]:
    """ffmpeg input options plus `-i <source>`; a webcam index is /dev/videoN on Linux, the
    avfoundation device index on macOS and the Nth DirectShow camera on Windows (or pass
    `video=<name>` directly)."""
    source = cfg.source
    if source.isdigit() and platform.startswith("win"):
        source = dshow_device(int(source))
    elif source.isdigit() and platform != "darwin":
        source = f"/dev/video{source}"
    return [*_input_args(cfg.source, platform), "-i", source]


def _scale(cfg: Config) -> str:
    return f"fps={cfg.fps},{_TRANSPOSE[cfg.rotate]}scale={cfg.width}:-2"


def ffmpeg_args(cfg: Config, platform: str = sys.platform) -> list[str]:
    rate = f"{cfg.bitrate_kbps}k"
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        *_input(cfg, platform),
        "-an",
        "-vf",
        _scale(cfg),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-pix_fmt",
        "yuv420p",
        "-g",
        str(cfg.fps * 2),
        "-b:v",
        rate,
        "-maxrate",
        rate,
        "-bufsize",
        f"{cfg.bitrate_kbps * 2}k",
        "-f",
        "rtsp",
        "-rtsp_transport",
        "tcp",
        publish_url(cfg),
    ]


def frames_ffmpeg_args(cfg: Config, platform: str = sys.platform) -> list[str]:
    """JPEG frames on stdout (image2pipe/mjpeg), upright, `width` px, `fps` per second."""
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        *_input(cfg, platform),
        "-an",
        "-vf",
        _scale(cfg),
        "-c:v",
        "mjpeg",
        "-q:v",
        str(cfg.jpeg_quality),
        "-f",
        "image2pipe",
        "pipe:1",
    ]


_SOI, _EOI = b"\xff\xd8", b"\xff\xd9"


class JpegSplitter:
    """Cuts a stream of concatenated JPEGs at their SOI/EOI markers. Inside a baseline JPEG's
    entropy-coded data every 0xFF is stuffed (FF 00), so FF D9 only appears as the EOI."""

    def __init__(self, max_bytes: int = 4 * 1024 * 1024) -> None:
        self._buf = bytearray()
        self._max = max_bytes

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buf += chunk
        out: list[bytes] = []
        while True:
            start = self._buf.find(_SOI)
            if start < 0:
                del self._buf[: max(len(self._buf) - 1, 0)]  # keep a trailing 0xFF
                break
            end = self._buf.find(_EOI, start + 2)
            if end < 0:
                del self._buf[:start]
                if len(self._buf) > self._max:  # garbage without an end marker
                    self._buf.clear()
                break
            out.append(bytes(self._buf[start : end + 2]))
            del self._buf[: end + 2]
        return out


def iter_jpegs(stream: IO[bytes], chunk_size: int = 65536) -> Iterator[bytes]:
    """Complete JPEGs from ffmpeg's stdout, as soon as each one ends."""
    splitter = JpegSplitter()
    read = getattr(stream, "read1", stream.read)
    while chunk := read(chunk_size):
        yield from splitter.feed(chunk)


class Newest:
    """A one-frame slot between the ffmpeg reader and the sender: a new frame replaces one the
    sender has not taken yet (counted as dropped), so a slow server never builds a queue."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._frame: bytes | None = None
        self.dropped = 0

    def put(self, frame: bytes) -> None:
        with self._cond:
            if self._frame is not None:
                self.dropped += 1
            self._frame = frame
            self._cond.notify()

    def take(self, timeout_s: float) -> bytes | None:
        with self._cond:
            if self._frame is None:
                self._cond.wait(timeout_s)
            frame, self._frame = self._frame, None
            return frame


def frame_request(cfg: Config) -> tuple[str, dict[str, str]]:
    """Path and headers of one frame POST (HTTP Basic with the publish credentials)."""
    base = urlsplit(cfg.push_url).path.rstrip("/")
    token = base64.b64encode(f"{cfg.user}:{cfg.password}".encode()).decode()
    headers = {
        "Authorization": f"Basic {token}",
        "Content-Type": "image/jpeg",
        "Connection": "keep-alive",
        "User-Agent": "aivee-connector",
    }
    return f"{base}/api/ingest/frames/{quote(cfg.camera_id, safe='')}", headers


class Connection(Protocol):
    def request(self, method: str, url: str, body: bytes, headers: Mapping[str, str]) -> None: ...
    def getresponse(self) -> http.client.HTTPResponse: ...
    def close(self) -> None: ...


def open_connection(push_url: str, timeout_s: float = 10.0) -> Connection:
    parts = urlsplit(push_url)
    host = parts.hostname or ""
    if parts.scheme == "https":
        return http.client.HTTPSConnection(host, parts.port or 443, timeout=timeout_s)
    return http.client.HTTPConnection(host, parts.port or 80, timeout=timeout_s)


_HINTS = {
    401: "credentials rejected: check STREAM_PUBLISH_USER/PASSWORD",
    404: "camera unknown to the cloud: add it in the dashboard with this camera id",
    413: "frame too large: lower CLOUD_WIDTH or raise CLOUD_JPEG_QUALITY",
}


class FramePusher:
    """POSTs the newest frame, one at a time, over one keep-alive connection; reconnects and
    backs off (1 s doubling to 30 s) on errors, dropping frames meanwhile."""

    def __init__(
        self,
        cfg: Config,
        connect: Callable[[str], Connection] = open_connection,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        report_every_s: float = 10.0,
    ) -> None:
        self._cfg = cfg
        self._connect = connect
        self._sleep = sleep
        self._clock = clock
        self._path, self._headers = frame_request(cfg)
        self._conn: Connection | None = None
        self._delay = 0.0
        self._report_every_s = report_every_s
        self._window_start = clock()
        self._window_sent = 0
        self.sent = 0

    def send(self, jpeg: bytes) -> bool:
        """One POST; True on 2xx. A failure backs off before returning."""
        try:
            if self._conn is None:
                self._conn = self._connect(self._cfg.push_url)
            self._conn.request("POST", self._path, jpeg, self._headers)
            resp = self._conn.getresponse()
            resp.read()  # drain it, so the connection can be reused
            status = resp.status
        except (OSError, http.client.HTTPException) as e:
            self._drop_connection()
            return self._failed(f"connection error: {e}")
        if 200 <= status < 300:
            self._delay = 0.0
            self.sent += 1
            self._window_sent += 1
            return True
        return self._failed(f"HTTP {status}: {_HINTS.get(status, 'server error')}")

    def _drop_connection(self) -> None:
        if self._conn is not None:
            self._conn.close()
        self._conn = None

    def _failed(self, why: str) -> bool:
        self._delay = min(self._delay * 2, 30.0) if self._delay else 1.0
        log.warning("frame not accepted (%s); retrying in %.0f s", why, self._delay)
        self._sleep(self._delay)
        return False

    def report(self, dropped: int) -> None:
        now = self._clock()
        span = now - self._window_start
        if span >= self._report_every_s:
            fps = self._window_sent / span
            log.info("push fps=%.1f sent=%d dropped=%d", fps, self.sent, dropped)
            self._window_start, self._window_sent = now, 0

    def run(self, slot: Newest, stop: threading.Event) -> None:
        while not stop.is_set():
            frame = slot.take(1.0)
            if frame is not None:
                self.send(frame)
            self.report(slot.dropped)
        self._drop_connection()


def run_push(cfg: Config) -> None:
    """ffmpeg -> JPEG frames -> newest-frame slot -> HTTPS POSTs; restarts ffmpeg with backoff."""
    args = frames_ffmpeg_args(cfg)
    log.info("pushing %s -> %s%s", cfg.source, cfg.push_url, frame_request(cfg)[0])
    slot, stop = Newest(), threading.Event()
    sender = threading.Thread(target=FramePusher(cfg).run, args=(slot, stop), daemon=True)
    sender.start()
    backoff = Backoff()
    try:
        while True:
            started = time.monotonic()
            with subprocess.Popen(args, stdout=subprocess.PIPE) as proc:
                assert proc.stdout is not None
                for frame in iter_jpegs(proc.stdout):
                    slot.put(frame)
                code = proc.wait()
            delay = backoff.next_delay(time.monotonic() - started)
            log.warning("ffmpeg exited with %s; restarting in %.0f s", code, delay)
            time.sleep(delay)
    finally:
        stop.set()


def redact(args: list[str], secret: str) -> list[str]:
    """Hide the password inside URL credentials (`user:<password>@host`) for logging."""
    if not secret:
        return list(args)
    marker = f":{quote(secret, safe='')}@"
    return [a.replace(marker, ":***@", 1) if "://" in a else a for a in args]


@dataclass
class Backoff:
    start_s: float = 1.0
    max_s: float = 30.0
    healthy_after_s: float = 60.0
    _current: float = 0.0

    def next_delay(self, ran_s: float) -> float:
        """Delay before restarting ffmpeg; a long healthy run resets the backoff."""
        if ran_s >= self.healthy_after_s or self._current == 0:
            self._current = self.start_s
        else:
            self._current = min(self._current * 2, self.max_s)
        return self._current


def run(cfg: Config) -> None:
    args = ffmpeg_args(cfg)
    log.info("pushing %s -> %s", cfg.source, " ".join(redact(args, cfg.password))[-80:])
    backoff = Backoff()
    while True:
        started = time.monotonic()
        code = subprocess.call(args)
        delay = backoff.next_delay(time.monotonic() - started)
        log.warning("ffmpeg exited with %s; restarting in %.0f s", code, delay)
        time.sleep(delay)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", help="camera URL, webcam index or video file (env SOURCE)")
    p.add_argument("--camera-id", help="camera id = MediaMTX path (env CAMERA_ID)")
    p.add_argument("--url", help="cloud MediaMTX base URL (env CLOUD_RTSP_URL)")
    p.add_argument(
        "--push", help="send JPEG frames over HTTPS to this AiVee URL (env CLOUD_PUSH_URL)"
    )
    p.add_argument("--rotate", type=int, help="0, 90, 180 or 270 clockwise (env ROTATE)")
    p.add_argument("--fps", type=int, help="frames per second sent (env CLOUD_FPS, default 5)")
    p.add_argument("--print", action="store_true", help="print the ffmpeg command and exit")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        cfg = Config.from_env(
            os.environ,
            source=a.source,
            camera_id=a.camera_id,
            url=a.url,
            rotate=a.rotate,
            fps=a.fps,
            push_url=a.push,
        )
    except ValueError as e:
        print(f"connector: {e}", file=sys.stderr)
        return 2
    if a.print:
        args = frames_ffmpeg_args(cfg) if cfg.push_url else ffmpeg_args(cfg)
        print(" ".join(redact(args, cfg.password)))
        return 0
    try:
        if cfg.push_url:
            run_push(cfg)
        else:
            run(cfg)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
