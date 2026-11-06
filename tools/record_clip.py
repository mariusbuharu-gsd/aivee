"""Record N seconds from a camera to an mp4, as a backup demo clip.

    uv run python tools/record_clip.py --source http://PHONE:8080/video --seconds 60 \\
        --rotate 90 --out recordings/sala-1.mp4
    make record SOURCE=http://PHONE:8080/video SECONDS=60 ROTATE=90 NAME=sala-1

Frames are rotated before they are written, so the clip is upright: replay it with
`make edge SOURCE=recordings/sala-1.mp4` and no ROTATE. Playback stays real time even when
the camera delivers fewer frames than --fps (a slow frame is repeated). `recordings/` is
gitignored.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aivee_edge.domain.ports import FrameSource

LIVE_RECONNECTS = 5


def copies_needed(written: int, elapsed_s: float, fps: float) -> int:
    """How many times to write the frame seen `elapsed_s` after the first one, so that the
    output's frame count follows wall time at `fps`."""
    return max(0, math.floor(elapsed_s * fps + 1e-6) + 1 - written)


def _is_live(source: str) -> bool:
    return source.isdigit() or "://" in source


def open_source(source: str, fps: float, rotate: int) -> FrameSource:
    from aivee_edge.adapters.capture import Cv2Source, FileSource

    if _is_live(source):
        return Cv2Source(source, fps, max_reconnects=LIVE_RECONNECTS, rotate=rotate)
    return FileSource(source, fps, rotate=rotate)


def record(source: FrameSource, out: Path, seconds: float, fps: float) -> int:
    """Write `seconds` of `source` to `out`; returns the number of frames written."""
    import cv2

    writer: Any = None
    written = 0
    start: float | None = None
    try:
        while written < seconds * fps:
            item = source.read()
            if item is None:
                break
            ts, image = item
            start = ts if start is None else start
            if writer is None:
                h, w = image.shape[:2]
                out.parent.mkdir(parents=True, exist_ok=True)
                writer = cv2.VideoWriter(str(out), cv2.VideoWriter.fourcc(*"mp4v"), fps, (w, h))
                if not writer.isOpened():
                    raise OSError(f"cannot write {out}")
            n = min(copies_needed(written, ts - start, fps), math.ceil(seconds * fps) - written)
            for _ in range(n):
                writer.write(image)
            written += n
    finally:
        if writer is not None:
            writer.release()
    return written


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--source", default="0", help="RTSP/HTTP URL, webcam index or video file")
    p.add_argument("--seconds", type=float, required=True, help="length of the clip")
    p.add_argument("--fps", type=float, default=15.0, help="frames per second written")
    p.add_argument("--rotate", type=int, default=0, choices=[0, 90, 180, 270])
    p.add_argument("--out", type=Path, default=None, help="default recordings/clip-<time>.mp4")
    args = p.parse_args(argv)
    out: Path = args.out or Path("recordings") / f"clip-{time.strftime('%Y%m%d-%H%M%S')}.mp4"

    try:
        source = open_source(args.source, args.fps, args.rotate)
    except (OSError, ValueError) as e:
        print(f"record_clip: cannot open {args.source}: {e}", file=sys.stderr)
        return 2
    print(f"record_clip: recording {args.seconds:.0f}s from {args.source} to {out}", flush=True)
    try:
        frames = record(source, out, args.seconds, args.fps)
    except KeyboardInterrupt:
        print("record_clip: interrupted, the clip is kept", flush=True)
        return 130
    except OSError as e:
        print(f"record_clip: {e}", file=sys.stderr)
        return 2
    finally:
        close = getattr(source, "close", None)
        if close is not None:
            close()
    if frames == 0:
        print(f"record_clip: no frames from {args.source}", file=sys.stderr)
        return 2
    print(f"record_clip: wrote {frames} frames ({frames / args.fps:.1f}s) to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
