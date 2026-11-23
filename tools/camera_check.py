"""Check IP cameras before an edge run: open each stream for a few seconds (8 by default)
and say what it delivers (resolution, fps, time to the first frame, codec). URLs are printed
without their passwords. Exit code 1 if any camera fails, 2 if no camera was given.

    make camera-check                                # every camera in CAMERAS (.env)
    uv run python tools/camera_check.py cam-01=rtsp://USER:PASS@192.168.1.21:554/stream2
    uv run python tools/camera_check.py --seconds 10 rtsp://USER:PASS@192.168.1.22:554/stream2

Prefer CAMERAS in .env over URLs on the command line: those end up in the shell history.
Streams are opened the way the edge opens them (RTSP over TCP, 5 s timeouts, one decoder
thread), so a camera that passes here works for `make edge-cameras`.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aivee_edge.redact import redact_url
from aivee_edge.settings import EdgeSettings, parse_cameras

DEFAULT_SECONDS = 8.0
POLL_S = 0.1
WARMUP_S = 2.0
"""fps is counted from this long after the first frame: FFmpeg probes the stream for a
second or two, then decodes that backlog in a burst, which would read as too many fps."""
DETECTION_PIXELS = 1920 * 1080
"""Above this the stream is probably the main stream: detection should use the substream."""

_clock: Callable[[], float] = time.monotonic
_sleep: Callable[[float], None] = time.sleep


@dataclass(frozen=True)
class Result:
    camera_id: str
    url: str
    ok: bool
    width: int | None = None
    height: int | None = None
    fps: float = 0.0
    first_frame_s: float | None = None
    codec: str | None = None
    seconds: float = DEFAULT_SECONDS
    fps_settled: bool = True
    """False: the run was too short to count fps past the start-up burst."""


def open_stream(url: str) -> Any:
    """The edge's own live source, giving up after one failed open."""
    from aivee_edge.adapters.capture import Cv2Source

    return Cv2Source(url, target_fps=0, max_reconnects=0)


def check(
    camera_id: str,
    url: str,
    seconds: float,
    *,
    open_stream: Callable[[str], Any] = open_stream,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Result:
    stream = open_stream(url)
    started = clock()
    first: float | None = None
    warm: tuple[float, int] | None = None  # (time, frames) once past the start-up burst
    stream.start()
    try:
        while clock() - started < seconds:
            health = stream.health()
            now = clock() - started
            if first is None and health.frames > 0:
                first = now
            elif first is not None and warm is None and now >= first + WARMUP_S:
                warm = (now, health.frames)
            if stream.ended():
                break
            sleep(POLL_S)
        health = stream.health()
        end = clock() - started
        gave_up = stream.ended()
    finally:
        stream.close()
    fps = health.fps
    settled = warm is not None and end - warm[0] >= 1.0
    if warm is not None and settled:
        fps = round((health.frames - warm[1]) / (end - warm[0]), 1)
    return Result(
        camera_id,
        url,
        ok=health.frames > 0 and fps > 0 and not gave_up,
        width=health.width,
        height=health.height,
        fps=fps,
        first_frame_s=first,
        codec=health.codec,
        seconds=seconds,
        fps_settled=settled,
    )


def describe(r: Result) -> str:
    shown = redact_url(r.url)
    if not r.ok:
        why = "no frame" if r.first_frame_s is None else "the stream stopped"
        return f"FAIL {r.camera_id}  {shown}  {why} within {r.seconds:.0f} s"
    size = f"{r.width}x{r.height}" if r.width and r.height else "?x?"
    first = f"{r.first_frame_s:.2f} s" if r.first_frame_s is not None else "?"
    line = (
        f"OK   {r.camera_id}  {shown}  {size}  {r.fps:.1f} fps  first frame {first}  "
        f"codec {r.codec or '?'}"
    )
    if not r.fps_settled:
        line += "  (fps counted during start-up: too high; use --seconds 8 or more)"
    if r.width and r.height and r.width * r.height > DETECTION_PIXELS:
        line += "  (main stream? detection should use the substream: Tapo /stream2, or 720p)"
    return line


def targets(args: list[str], cameras: str) -> list[tuple[str, str]]:
    """(id, url) from the arguments (`url` or `id=url`), else from CAMERAS."""
    if not args:
        return [(c.id, c.source) for c in parse_cameras(cameras)]
    out: list[tuple[str, str]] = []
    for i, arg in enumerate(args, 1):
        head, sep, tail = arg.partition("=")
        if sep and "://" not in head:
            out.append((head, tail))
        else:
            out.append((f"camera-{i}", arg))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="camera_check", description=__doc__.split("\n\n")[0])
    p.add_argument("urls", nargs="*", help="camera URL or id=URL (default: CAMERAS from .env)")
    p.add_argument("--seconds", type=float, default=DEFAULT_SECONDS, help="per camera")
    p.add_argument("--env-file", default=".env", help="where CAMERAS is read from")
    args = p.parse_args(argv)
    cameras = "" if args.urls else EdgeSettings(_env_file=args.env_file).cameras  # type: ignore[call-arg]
    try:
        todo = targets(args.urls, cameras)
    except ValueError as e:
        print(f"camera_check: {e}", file=sys.stderr)
        return 2
    if not todo:
        print("camera_check: no camera: pass URLs or set CAMERAS in .env", file=sys.stderr)
        return 2
    failed = 0
    for camera_id, url in todo:
        print(f"...  {camera_id}  {redact_url(url)}  opening for {args.seconds:.0f} s", flush=True)
        result = check(
            camera_id, url, args.seconds, open_stream=open_stream, clock=_clock, sleep=_sleep
        )
        failed += not result.ok
        print(describe(result), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
