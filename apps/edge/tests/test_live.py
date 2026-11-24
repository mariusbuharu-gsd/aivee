"""The edge box relays each running camera into MediaMTX for the dashboard's live view."""

import logging

import pytest
from aivee_edge.live import LiveRelays, live_command, publish_url


class Proc:
    def __init__(self, args: list[str]) -> None:
        self.args = args
        self.code: int | None = None
        self.terminated = False

    def poll(self) -> int | None:
        return self.code

    def terminate(self) -> None:
        self.terminated = True
        self.code = -15

    def wait(self, timeout: float | None = None) -> int:
        return self.code or 0


class Spawner:
    def __init__(self) -> None:
        self.procs: list[Proc] = []

    def __call__(self, camera_id: str, args: list[str]) -> Proc:
        proc = Proc(args)
        self.procs.append(proc)
        return proc


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


SRC = "rtsp://admin:s3cret@10.0.0.5:554/stream2"


def _relays(spawn: Spawner, clock: Clock) -> LiveRelays:
    return LiveRelays("rtsp://localhost:8554", "pub", "pw", spawn=spawn, clock=clock)


def test_the_publish_url_carries_the_credentials_and_the_camera_id() -> None:
    assert publish_url("rtsp://srv:8554/", "u", "p@ss", "cam-1") == "rtsp://u:p%40ss@srv:8554/cam-1"
    assert publish_url("rtsp://srv:8554", "", "", "cam-1") == "rtsp://srv:8554/cam-1"


def test_an_rtsp_camera_is_copied_without_re_encoding_or_sound() -> None:
    args = live_command(SRC, "rtsp://u:p@srv:8554/cam-1")
    assert args[0] == "ffmpeg"
    pull = args[: args.index("-i")]
    assert pull[pull.index("-rtsp_transport") + 1] == "tcp"
    assert args[args.index("-i") + 1] == SRC
    assert args[args.index("-c:v") : args.index("-c:v") + 2] == ["-c:v", "copy"]
    assert "-an" in args
    assert args[-1] == "rtsp://u:p@srv:8554/cam-1"


def test_an_mjpeg_camera_is_encoded_to_h264_for_webrtc() -> None:
    args = live_command("http://10.0.0.9:8080/video", "rtsp://srv:8554/cam-2")
    assert "-rtsp_transport" not in args[: args.index("-i")]
    assert args[args.index("-c:v") + 1] == "libx264"
    assert "zerolatency" in args


def test_sync_starts_one_relay_per_camera_and_stops_removed_ones() -> None:
    spawn, clock = Spawner(), Clock()
    relays = _relays(spawn, clock)
    relays.sync({"cam-1": SRC, "cam-2": "rtsp://10.0.0.6/stream2"})
    assert len(spawn.procs) == 2
    assert spawn.procs[0].args[-1] == "rtsp://pub:pw@localhost:8554/cam-1"

    relays.sync({"cam-2": "rtsp://10.0.0.6/stream2"})
    assert spawn.procs[0].terminated
    assert not spawn.procs[1].terminated
    assert relays.running() == ["cam-2"]


def test_a_changed_source_restarts_that_relay() -> None:
    spawn, clock = Spawner(), Clock()
    relays = _relays(spawn, clock)
    relays.sync({"cam-1": SRC})
    relays.sync({"cam-1": "rtsp://admin:s3cret@10.0.0.5:554/stream1"})
    assert spawn.procs[0].terminated
    assert len(spawn.procs) == 2
    assert "stream1" in spawn.procs[1].args[spawn.procs[1].args.index("-i") + 1]


def test_a_dead_relay_restarts_after_a_growing_pause() -> None:
    spawn, clock = Spawner(), Clock()
    relays = _relays(spawn, clock)
    relays.sync({"cam-1": SRC})
    spawn.procs[0].code = 1  # camera or MediaMTX went away
    relays.sync({"cam-1": SRC})
    assert len(spawn.procs) == 1  # waits first
    clock.now = 2.0
    relays.sync({"cam-1": SRC})
    assert len(spawn.procs) == 2

    spawn.procs[1].code = 1
    clock.now = 3.0
    relays.sync({"cam-1": SRC})
    clock.now = 4.5
    relays.sync({"cam-1": SRC})
    assert len(spawn.procs) == 2  # the second pause is longer
    clock.now = 7.5
    relays.sync({"cam-1": SRC})
    assert len(spawn.procs) == 3


def test_a_relay_that_ran_a_while_restarts_quickly_again() -> None:
    spawn, clock = Spawner(), Clock()
    relays = _relays(spawn, clock)
    relays.sync({"cam-1": SRC})
    spawn.procs[0].code = 1
    relays.sync({"cam-1": SRC})
    clock.now = 2.0
    relays.sync({"cam-1": SRC})
    clock.now = 600.0  # streamed for ten minutes, then dropped
    spawn.procs[1].code = 1
    relays.sync({"cam-1": SRC})
    clock.now = 602.0
    relays.sync({"cam-1": SRC})
    assert len(spawn.procs) == 3


def test_stop_all_terminates_every_relay() -> None:
    spawn, clock = Spawner(), Clock()
    relays = _relays(spawn, clock)
    relays.sync({"cam-1": SRC, "cam-2": SRC})
    relays.stop_all()
    assert all(p.terminated for p in spawn.procs)
    assert relays.running() == []


def test_logs_never_show_a_password(caplog: pytest.LogCaptureFixture) -> None:
    spawn, clock = Spawner(), Clock()
    caplog.set_level(logging.INFO, logger="aivee_edge.live")
    relays = _relays(spawn, clock)
    relays.sync({"cam-1": SRC})
    spawn.procs[0].code = 1
    relays.sync({"cam-1": SRC})
    relays.stop_all()
    assert "live_started camera=cam-1" in caplog.text
    assert "s3cret" not in caplog.text
    assert ":pw@" not in caplog.text


def test_without_ffmpeg_nothing_is_spawned(caplog: pytest.LogCaptureFixture) -> None:
    spawn, clock = Spawner(), Clock()
    relays = LiveRelays("rtsp://localhost:8554", "pub", "pw", spawn=spawn, clock=clock, ffmpeg=None)
    relays.sync({"cam-1": SRC})
    relays.sync({"cam-1": SRC})
    assert spawn.procs == []
    assert caplog.text.count("ffmpeg not found") == 1
