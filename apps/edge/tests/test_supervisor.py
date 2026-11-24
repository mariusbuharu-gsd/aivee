"""Several cameras in one edge process: each runs on its own thread, a failing one restarts
and never stops the others."""

import threading
import time
from collections.abc import Callable

from aivee_edge.supervisor import CameraRun, Supervisor


def _until(cond: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.005)


class Steady:
    """A pipeline that runs until stopped, counting its turns."""

    def __init__(self) -> None:
        self.runs = 0
        self.running = threading.Event()

    def run(self, stop: threading.Event | None = None) -> int:
        self.runs += 1
        self.running.set()
        assert stop is not None
        stop.wait()
        return 42


class FailsOnce(Steady):
    def run(self, stop: threading.Event | None = None) -> int:
        if self.runs == 0:
            self.runs += 1
            raise RuntimeError("decoder exploded")
        return super().run(stop)


class Ends:
    """A pipeline whose source ended (a clip, or a camera that gave up)."""

    def run(self, stop: threading.Event | None = None) -> int:
        return 3


class Source:
    def __init__(self) -> None:
        self.closed = False

    def read(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def test_a_failing_camera_restarts_and_the_others_keep_running() -> None:
    steady, flaky = Steady(), FailsOnce()
    sources = [Source(), Source()]
    sup = Supervisor(
        [CameraRun("cam-01", steady, sources[0]), CameraRun("cam-02", flaky, sources[1])],
        restart_after_s=0.01,
    )
    stop = threading.Event()
    done: list[int] = []
    thread = threading.Thread(target=lambda: done.append(sup.run(stop)))
    thread.start()
    _until(lambda: steady.running.is_set() and flaky.running.is_set())
    assert flaky.runs == 2 and steady.runs == 1
    stop.set()
    thread.join(5)
    assert done == [0]
    assert all(s.closed for s in sources)


def test_the_process_ends_when_every_camera_has_ended() -> None:
    sup = Supervisor([CameraRun("cam-01", Ends(), Source()), CameraRun("cam-02", Ends(), Source())])
    assert sup.run(threading.Event()) == 0


def test_one_ended_camera_does_not_end_the_others() -> None:
    steady = Steady()
    sup = Supervisor([CameraRun("cam-01", Ends(), Source()), CameraRun("cam-02", steady, Source())])
    stop = threading.Event()
    thread = threading.Thread(target=sup.run, args=(stop,))
    thread.start()
    _until(steady.running.is_set)
    time.sleep(0.05)
    assert thread.is_alive()
    stop.set()
    thread.join(5)
    assert not thread.is_alive()
