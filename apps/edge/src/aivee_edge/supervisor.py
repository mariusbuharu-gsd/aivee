"""Several cameras in one edge process (audit V8, Q15).

One thread per camera runs that camera's `EdgePipeline` (its own source, detector, pose and
visual scorer: the trackers are stateful). The pipelines share one MQTT connection. A
pipeline that raises is logged and restarted after `restart_after_s`; one whose source ends
(a clip, a camera that gave up) stops alone. Stopping closes the sources so a read that waits
for a frame returns.

Cameras can join (`add`) and leave (`remove`) while the supervisor runs, without touching the
others: the edge box follows the cameras the dashboard configures. With `keep_running` the
supervisor runs until `stop` even with no camera left (an edge box waiting for its cameras);
otherwise the process ends when every camera has ended.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

log = logging.getLogger("aivee_edge.supervisor")

RESTART_AFTER_S = 5.0
POLL_S = 0.5
JOIN_S = 5.0


class Runnable(Protocol):
    def run(self, stop: threading.Event | None = None) -> int: ...


@dataclass
class CameraRun:
    camera_id: str
    pipeline: Runnable
    source: object
    """The pipeline's frame source; closed on stop when it has `close()`."""


@dataclass
class _Running:
    cam: CameraRun
    stop: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None


def _close(source: object) -> None:
    close = getattr(source, "close", None)
    if callable(close):
        close()


class Supervisor:
    def __init__(
        self,
        cameras: list[CameraRun],
        *,
        restart_after_s: float = RESTART_AFTER_S,
        tick: Callable[[], None] | None = None,
        tick_s: float = POLL_S,
        keep_running: bool = False,
    ) -> None:
        """`tick`, when given, is called on the supervisor's thread every `tick_s` while
        it runs (camera health reports, following the device's config)."""
        self._restart_after_s = restart_after_s
        self._tick = tick
        self._tick_s = tick_s
        self._keep_running = keep_running
        self._lock = threading.Lock()
        self._running: dict[str, _Running] = {}
        self._stopped: list[_Running] = []
        self._started = False
        for cam in cameras:
            self.add(cam)

    def camera_ids(self) -> list[str]:
        with self._lock:
            return list(self._running)

    def add(self, cam: CameraRun) -> None:
        """Run one more camera (at once when the supervisor is running)."""
        with self._lock:
            if cam.camera_id in self._running:
                raise ValueError(f"camera {cam.camera_id!r} is already running")
            entry = _Running(cam)
            self._running[cam.camera_id] = entry
            if self._started:
                self._launch(entry)

    def remove(self, camera_id: str) -> None:
        """Stop one camera: its pipeline returns at its next frame, its source is closed so a
        waiting read returns. The others keep running. Unknown ids are ignored."""
        with self._lock:
            entry = self._running.pop(camera_id, None)
            if entry is None:
                return
            self._stopped.append(entry)
        entry.stop.set()
        _close(entry.cam.source)

    def _launch(self, entry: _Running) -> None:
        entry.thread = threading.Thread(
            target=self._run_camera, args=(entry,), name=f"camera {entry.cam.camera_id}"
        )
        entry.thread.start()

    def _alive(self) -> bool:
        with self._lock:
            return any(e.thread is not None and e.thread.is_alive() for e in self._running.values())

    def run(self, stop: threading.Event) -> int:
        """Run every camera until `stop` is set (or, without `keep_running`, until all have
        ended); returns the exit code."""
        with self._lock:
            self._started = True
            for entry in self._running.values():
                self._launch(entry)
        try:
            while not stop.is_set() and (self._keep_running or self._alive()):
                stop.wait(self._tick_s)
                if self._tick is not None and not stop.is_set():
                    try:
                        self._tick()
                    except Exception:
                        log.exception("supervisor tick failed")
        finally:
            stop.set()
            with self._lock:
                entries = [*self._running.values(), *self._stopped]
                self._running.clear()
            for entry in entries:
                entry.stop.set()
                _close(entry.cam.source)
            for entry in entries:
                if entry.thread is not None:
                    entry.thread.join(timeout=JOIN_S)
        return 0

    def _run_camera(self, entry: _Running) -> None:
        cam, stop = entry.cam, entry.stop
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
