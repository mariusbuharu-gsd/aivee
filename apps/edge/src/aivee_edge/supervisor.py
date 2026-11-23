"""Several cameras in one edge process (audit V8, Q15).

One thread per camera runs that camera's `EdgePipeline` (its own source, detector, pose and
visual scorer: the trackers are stateful). The pipelines share one MQTT connection. A
pipeline that raises is logged and restarted after `restart_after_s`; one whose source ends
(a clip, a camera that gave up) stops alone. The process ends when every camera has ended
or on `stop`; stopping closes the sources so a read that waits for a frame returns.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger("aivee_edge.supervisor")

RESTART_AFTER_S = 5.0
POLL_S = 0.5


class Runnable(Protocol):
    def run(self, stop: threading.Event | None = None) -> int: ...


@dataclass
class CameraRun:
    camera_id: str
    pipeline: Runnable
    source: object
    """The pipeline's frame source; closed on stop when it has `close()`."""


class Supervisor:
    def __init__(
        self,
        cameras: list[CameraRun],
        *,
        restart_after_s: float = RESTART_AFTER_S,
        tick: Callable[[], None] | None = None,
        tick_s: float = POLL_S,
    ) -> None:
        """`tick`, when given, is called on the supervisor's thread every `tick_s` while
        the cameras run (camera health reports)."""
        self._cameras = cameras
        self._restart_after_s = restart_after_s
        self._tick = tick
        self._tick_s = tick_s

    def run(self, stop: threading.Event) -> int:
        """Run every camera until all have ended or `stop` is set; returns the exit code."""
        threads = [
            threading.Thread(
                target=self._run_camera, args=(cam, stop), name=f"camera {cam.camera_id}"
            )
            for cam in self._cameras
        ]
        for thread in threads:
            thread.start()
        try:
            while not stop.is_set() and any(t.is_alive() for t in threads):
                stop.wait(self._tick_s)
                if self._tick is not None and not stop.is_set():
                    try:
                        self._tick()
                    except Exception:
                        log.exception("camera health report failed")
        finally:
            stop.set()
            for cam in self._cameras:
                close = getattr(cam.source, "close", None)
                if callable(close):
                    close()
            for thread in threads:
                thread.join(timeout=5.0)
        return 0

    def _run_camera(self, cam: CameraRun, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                frames = cam.pipeline.run(stop)
            except Exception:
                log.exception(
                    "camera_failed camera=%s restarting_in=%.0fs",
                    cam.camera_id,
                    self._restart_after_s,
                )
                stop.wait(self._restart_after_s)
                continue
            if not stop.is_set():
                log.warning("camera_ended camera=%s frames=%d", cam.camera_id, frames)
            return
