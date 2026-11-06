"""AiVee stream connector (cloud mode, restaurant side).

Pulls one camera on the restaurant network (RTSP, phone MJPEG, webcam index or a video file)
and pushes a small H.264 stream to the AiVee cloud (MediaMTX). It does no analysis and stores
nothing: the cloud vision worker analyses the frames in memory.

Standard library only, so it runs on any PC or small box that has Python 3 and ffmpeg.

    python3 connector.py --source http://PHONE:8080/video --camera-id cam-01 --rotate 90

Env: SOURCE, CAMERA_ID, CLOUD_RTSP_URL, STREAM_PUBLISH_USER, STREAM_PUBLISH_PASSWORD,
CLOUD_FPS, CLOUD_WIDTH, CLOUD_BITRATE_KBPS, ROTATE. Flags override env.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
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

    def __post_init__(self) -> None:
        if not _CAMERA_ID.match(self.camera_id):
            raise ValueError("CAMERA_ID may contain only letters, digits, '-' and '_'")
        if self.rotate not in _TRANSPOSE:
            raise ValueError(f"ROTATE must be one of {sorted(_TRANSPOSE)}")
        if not self.source:
            raise ValueError("SOURCE is required")
        if self.fps < 1 or self.width < 160 or self.bitrate_kbps < 50:
            raise ValueError("fps >= 1, width >= 160 and bitrate >= 50 kbps")

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


def _input_args(source: str) -> list[str]:
    if source.startswith(("rtsp://", "rtsps://")):
        return ["-rtsp_transport", "tcp"]
    if source.startswith(("http://", "https://")):
        # Phone MJPEG streams carry no timestamps.
        return ["-use_wallclock_as_timestamps", "1"]
    if source.isdigit():
        return ["-f", "v4l2"]
    return ["-re", "-stream_loop", "-1"]  # a recorded file, replayed in real time


def ffmpeg_args(cfg: Config) -> list[str]:
    source = f"/dev/video{cfg.source}" if cfg.source.isdigit() else cfg.source
    rate = f"{cfg.bitrate_kbps}k"
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        *_input_args(cfg.source),
        "-i",
        source,
        "-an",
        "-vf",
        f"fps={cfg.fps},{_TRANSPOSE[cfg.rotate]}scale={cfg.width}:-2",
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
        )
    except ValueError as e:
        print(f"connector: {e}", file=sys.stderr)
        return 2
    if a.print:
        print(" ".join(redact(ffmpeg_args(cfg), cfg.password)))
        return 0
    try:
        run(cfg)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
