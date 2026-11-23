"""How a live camera stream is doing, as the capture adapter measures it."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceHealth:
    """A snapshot of one live source.

    `connected`: the stream is open and its last read succeeded (False while reconnecting).
    `last_frame_age_s`: seconds since the newest decoded frame, None before the first one.
    `fps`: frames the camera delivered per second over the last few seconds (before any
    drop to the pipeline's target fps). `width`/`height`: of the camera picture, before
    rotation; None before the first frame. `frames`: decoded since start. `reconnects`:
    failed opens and dropped streams since start.
    """

    connected: bool
    last_frame_age_s: float | None
    fps: float
    width: int | None = None
    height: int | None = None
    frames: int = 0
    reconnects: int = 0
