"""The dashboard's live view: the edge box relays each camera it runs into MediaMTX.

The dashboard plays `http://<host>:8889/<camera_id>` over WebRTC; something must publish
`rtsp://<host>:8554/<camera_id>`. On an edge box that is this module: one `ffmpeg` per running
camera, pulling the camera a second time and pushing it to MediaMTX with the publish
credentials (STREAM_PUBLISH_USER/PASSWORD). An RTSP camera is copied as it is (no decoding,
almost no CPU); an MJPEG camera (a phone) is encoded to H.264, which WebRTC plays.

Nothing is recorded or analysed here. A relay that dies (camera rebooting, MediaMTX restarted)
starts again after a pause that doubles up to a minute, and drops back to a short pause once a
relay has streamed for a minute. Passwords never reach the log.
"""

import logging
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import IO, Protocol
from urllib.parse import quote, urlsplit, urlunsplit

from aivee_edge.redact import redact_text, redact_url

log = logging.getLogger("aivee_edge.live")

FIRST_PAUSE_S = 2.0
MAX_PAUSE_S = 60.0
HEALTHY_AFTER_S = 60.0
"""A relay that streamed this long counts as healthy: its next failure waits only briefly."""


class Process(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


Spawn = Callable[[str, list[str]], Process]
"""Start one relay: (camera id, ffmpeg command) → the running process."""


def publish_url(base: str, user: str, password: str, camera_id: str) -> str:
    """`rtsp://host:8554` + credentials + camera id → the URL ffmpeg publishes to."""
    parts = urlsplit(base.rstrip("/"))
    host = parts.netloc.rpartition("@")[2]
    if user:
        host = f"{quote(user, safe='')}:{quote(password, safe='')}@{host}"
    return urlunsplit((parts.scheme, host, f"{parts.path}/{camera_id}", "", ""))


def live_command(source: str, target: str, ffmpeg: str = "ffmpeg") -> list[str]:
    """The ffmpeg command relaying `source` to `target` (RTSP), video only."""
    head = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin"]
    if source.lower().startswith(("rtsp://", "rtsps://")):
        pull = ["-rtsp_transport", "tcp", "-timeout", "10000000", "-i", source]
        video = ["-c:v", "copy"]
    else:
        pull = ["-i", source]
        video = [
            "-vf", "scale=640:-2,fps=10", "-c:v", "libx264", "-preset", "veryfast",
            "-tune", "zerolatency", "-pix_fmt", "yuv420p", "-g", "20", "-b:v", "600k",
        ]  # fmt: skip
    return [*head, *pull, "-an", *video, "-f", "rtsp", "-rtsp_transport", "tcp", target]


def _log_stderr(camera_id: str, stream: IO[bytes]) -> None:
    for raw in stream:
        line = raw.decode(errors="replace").strip()
        if line:
            log.warning("live_ffmpeg camera=%s: %s", camera_id, redact_text(line))


def spawn_ffmpeg(camera_id: str, args: list[str]) -> Process:
    """Start ffmpeg with its errors (credentials masked) in the edge log."""
    proc = subprocess.Popen(
        args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    if proc.stderr is not None:
        threading.Thread(target=_log_stderr, args=(camera_id, proc.stderr), daemon=True).start()
    return proc


@dataclass
class _Relay:
    source: str
    proc: Process | None
    started_at: float
    failures: int = 0
    retry_at: float = 0.0


class LiveRelays:
    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        *,
        spawn: Spawn = spawn_ffmpeg,
        clock: Callable[[], float],
        ffmpeg: str | None = "ffmpeg",
    ) -> None:
        """`spawn` starts one relay process (default: ffmpeg, errors to the log).
        `ffmpeg=None`: ffmpeg is not installed; the live view stays off, said once."""
        self._base = base_url
        self._user = user
        self._password = password
        self._spawn = spawn
        self._clock = clock
        self._ffmpeg = ffmpeg
        self._relays: dict[str, _Relay] = {}
        self._warned = False

    def running(self) -> list[str]:
        return sorted(self._relays)

    def sync(self, wanted: dict[str, str]) -> None:
        """Relay exactly the cameras in `wanted` (camera id → source)."""
        if self._ffmpeg is None:
            if wanted and not self._warned:
                log.error("live view off: ffmpeg not found on this box (apt install ffmpeg)")
                self._warned = True
            return
        for camera_id in list(self._relays):
            if wanted.get(camera_id) != self._relays[camera_id].source:
                self._stop(camera_id, "removed" if camera_id not in wanted else "changed")
        now = self._clock()
        for camera_id, source in wanted.items():
            relay = self._relays.get(camera_id)
            if relay is None:
                self._relays[camera_id] = _Relay(source, self._start(camera_id, source), now)
                continue
            if relay.proc is not None:
                code = relay.proc.poll()
                if code is None:
                    continue
                healthy = now - relay.started_at >= HEALTHY_AFTER_S
                relay.failures = 1 if healthy else relay.failures + 1
                pause = min(FIRST_PAUSE_S * 2 ** (relay.failures - 1), MAX_PAUSE_S)
                relay.proc, relay.retry_at = None, now + pause
                log.warning("live_stopped camera=%s code=%d retry_in=%.0fs", camera_id, code, pause)
            if now >= relay.retry_at:
                relay.proc, relay.started_at = self._start(camera_id, source), now

    def stop_all(self) -> None:
        for camera_id in list(self._relays):
            self._stop(camera_id, "stopping")

    def _start(self, camera_id: str, source: str) -> Process:
        target = publish_url(self._base, self._user, self._password, camera_id)
        args = live_command(source, target, self._ffmpeg or "ffmpeg")
        proc = self._spawn(camera_id, args)
        log.info(
            "live_started camera=%s source=%s to=%s",
            camera_id,
            redact_url(source),
            redact_url(target),
        )
        return proc

    def _stop(self, camera_id: str, why: str) -> None:
        relay = self._relays.pop(camera_id)
        if relay.proc is not None and relay.proc.poll() is None:
            relay.proc.terminate()
            try:
                relay.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log.warning("live_relay camera=%s did not stop in 5 s", camera_id)
        log.info("live_stopped camera=%s reason=%s", camera_id, why)
