"""Print the CLIP score of a `visual` rule's prompts per image or per video frame.

The score is what the edge compares with the condition's `threshold`: the softmax share of
the positive prompts against the negative ones, with the model's own temperature.

uv run python tools/visual_probe.py fire.jpg "a photo of fire" "flames" \\
    --negative "a photo of a normal restaurant room" "people sitting at tables"
uv run python tools/visual_probe.py recordings/sala-1.mp4 "smoke" --negative "a room" --every 15
uv run python tools/visual_probe.py data/snapshots/ "a bear" --negative "a room" --threshold 0.5
uv run python tools/visual_probe.py frame.jpg "water on the floor" --negative "a dry floor" \\
    --box 0.2,0.5,0.8,1.0          # score a zone's bounding box only (normalised x1,y1,x2,y2)

A directory scores every .jpg/.jpeg/.png in it. Run from the repo root (`uv run`).
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import cv2
from aivee_edge.adapters.clip_visual import ClipVisualScorer
from aivee_edge.domain.observation import BBox

IMAGES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def frames(path: Path, every: int) -> Iterator[tuple[str, Any]]:
    if path.is_dir():
        for p in sorted(path.iterdir()):
            if p.suffix.lower() in IMAGES:
                yield from frames(p, every)
        return
    if path.suffix.lower() in IMAGES:
        image = cv2.imread(str(path))
        if image is None:
            raise SystemExit(f"cannot read {path}")
        yield path.name, image
        return
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f"cannot open {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    i = 0
    while True:
        ok, image = cap.read()
        if not ok:
            break
        if i % every == 0:
            label = f"{path.name}@{i / fps:6.1f}s" if fps else f"{path.name}#{i}"
            yield label, image
        i += 1
    cap.release()


def parse_box(text: str | None) -> BBox | None:
    if not text:
        return None
    x1, y1, x2, y2 = (float(v) for v in text.split(","))
    return (x1, y1, x2, y2)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("source", type=Path, help="image, video or directory of images")
    p.add_argument("positive", nargs="+", help="English prompts of what to find")
    p.add_argument("--negative", nargs="*", default=[], help="English contrast prompts")
    p.add_argument("--every", type=int, default=10, help="video: score every Nth frame")
    p.add_argument("--box", help="normalised x1,y1,x2,y2 crop (a zone's box); default frame")
    p.add_argument("--threshold", type=float, help="also print MATCH at or above this score")
    args = p.parse_args(argv)

    scorer = ClipVisualScorer()
    scorer.prepare([*args.positive, *args.negative])
    print(f"logit_scale={scorer.logit_scale:.1f} positive={args.positive} negative={args.negative}")
    box = parse_box(args.box)
    scores: list[float] = []
    for label, image in frames(args.source, max(1, args.every)):
        started = time.perf_counter()
        score = scorer.score(image, box, args.positive, args.negative)
        ms = (time.perf_counter() - started) * 1000
        scores.append(score)
        verdict = ""
        if args.threshold is not None:
            verdict = "  MATCH" if score >= args.threshold else ""
        print(f"{label:<48} score={score:.3f}  {ms:4.0f} ms{verdict}")
    if not scores:
        print("no frames", file=sys.stderr)
        return 1
    print(f"n={len(scores)} min={min(scores):.3f} max={max(scores):.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
