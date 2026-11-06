"""`python -m aivee_edge --source <url|file|index>`: the live edge device."""

import argparse
import sys

from aivee_edge.app import configure_logging, run
from aivee_edge.settings import ROTATIONS, EdgeSettings


def parse(argv: list[str] | None = None) -> EdgeSettings:
    p = argparse.ArgumentParser(prog="aivee_edge", description=__doc__)
    p.add_argument("--source", help="RTSP/HTTP URL, webcam index or video file (env SOURCE)")
    p.add_argument("--fps", type=float, help="target frames per second (env TARGET_FPS)")
    p.add_argument("--camera-id", help="camera id the rules refer to (env CAMERA_ID)")
    p.add_argument(
        "--rotate",
        type=int,
        choices=ROTATIONS,
        help="rotate frames clockwise before detection (env ROTATE)",
    )
    p.add_argument("--loop", action="store_true", help="loop a video file")
    p.add_argument("--no-pose", action="store_true", help="disable raised-hand detection")
    p.add_argument("--appearance", action="store_true", help="enable CLIP appearance scoring")
    p.add_argument("--no-blur", action="store_true", help="publish alerts without snapshots")
    args = p.parse_args(argv)

    overrides: dict[str, object] = {}
    if args.source is not None:
        overrides["source"] = args.source
    if args.fps is not None:
        overrides["target_fps"] = args.fps
    if args.camera_id is not None:
        overrides["camera_id"] = args.camera_id
    if args.rotate is not None:
        overrides["rotate"] = args.rotate
    if args.loop:
        overrides["loop_file"] = True
    if args.no_pose:
        overrides["pose_model"] = ""
    if args.appearance:
        overrides["appearance"] = True
    if args.no_blur:
        overrides["blur"] = False
    return EdgeSettings(**overrides)  # type: ignore[arg-type]


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    return run(parse(argv))


if __name__ == "__main__":
    sys.exit(main())
