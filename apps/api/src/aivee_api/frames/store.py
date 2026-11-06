"""Cloud mode over HTTPS: the newest JPEG of each camera, in memory only.

A connector on the restaurant's network POSTs frames to `/api/ingest/frames/{camera}`; the API
keeps the newest one per camera here (for `live.mjpg`) and relays each to the camera's vision
worker over internal MQTT. Frames are never written to disk.

**Single replica only.** The store lives in one process: with two api replicas a dashboard
could read from the replica the connector does not post to. Scaling out needs a shared hub
(the vision worker already gets frames through MQTT, so live.mjpg could subscribe too).
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from aivee_api.edge.publisher import EdgePublisher, PublisherUnavailable

log = logging.getLogger(__name__)

QOS_FRAMES = 0
BOUNDARY = "aiveeframe"
JPEG_MAGIC = b"\xff\xd8\xff"


def is_jpeg(data: bytes) -> bool:
    return data.startswith(JPEG_MAGIC)


@dataclass(frozen=True)
class LiveFrame:
    jpeg: bytes
    at: float
    """Wall-clock time (`time.time()`) the API received it."""
    seq: int


class LiveFrames:
    """Newest frame per camera plus a wake-up for `live.mjpg` readers. One event loop only."""

    def __init__(
        self,
        publisher: EdgePublisher | None = None,
        *,
        max_age_s: float = 10.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._publisher = publisher
        self._max_age_s = max_age_s
        self._clock = clock
        self._frames: dict[str, LiveFrame] = {}
        self._waiters: dict[str, asyncio.Event] = {}
        self._seq = 0
        self._relay_failed = False

    def put(self, camera_id: str, jpeg: bytes) -> LiveFrame:
        self._seq += 1
        frame = LiveFrame(jpeg, self._clock(), self._seq)
        self._frames[camera_id] = frame
        waiter = self._waiters.pop(camera_id, None)
        if waiter is not None:
            waiter.set()
        return frame

    def latest(self, camera_id: str) -> LiveFrame | None:
        """The newest frame, or None when there is none younger than `max_age_s`."""
        frame = self._frames.get(camera_id)
        if frame is None or self._clock() - frame.at > self._max_age_s:
            return None
        return frame

    async def next_after(self, camera_id: str, seq: int, timeout_s: float) -> LiveFrame | None:
        """The newest frame newer than `seq`, waiting up to `timeout_s` for one."""
        frame = self.latest(camera_id)
        if frame is not None and frame.seq > seq:
            return frame
        waiter = self._waiters.setdefault(camera_id, asyncio.Event())
        try:
            await asyncio.wait_for(waiter.wait(), timeout_s)
        except TimeoutError:
            return None
        frame = self.latest(camera_id)
        return frame if frame is not None and frame.seq > seq else None

    async def relay(self, topic: str, jpeg: bytes) -> bool:
        """Publish to the vision worker (QoS 0, not retained). A broker outage drops the frame:
        live frames are worthless late, and the worker's stream-gap handling covers the hole."""
        if self._publisher is None:
            return False
        try:
            await self._publisher.publish(topic, jpeg, qos=QOS_FRAMES, retain=False)
        except PublisherUnavailable as e:
            if not self._relay_failed:
                log.warning("frame relay unavailable (%s); dropping frames", e)
            self._relay_failed = True
            return False
        self._relay_failed = False
        return True


def mjpeg_part(jpeg: bytes) -> bytes:
    head = f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpeg)}\r\n\r\n"
    return head.encode() + jpeg + b"\r\n"


async def mjpeg_stream(
    frames: LiveFrames,
    camera_id: str,
    *,
    fps: float,
    disconnected: Callable[[], Awaitable[bool]],
    idle_s: float = 30.0,
    poll_s: float = 1.0,
    clock: Callable[[], float] = time.monotonic,
) -> AsyncIterator[bytes]:
    """multipart/x-mixed-replace parts of the newest frames, at most `fps` per second.

    Ends when the client goes away (checked at least every `poll_s`) or no frame came for
    `idle_s` (the connector stopped; the dashboard reconnects)."""
    period = 1.0 / fps if fps > 0 else 0.0
    seq = -1
    last_frame = clock()
    while not await disconnected():
        frame = await frames.next_after(camera_id, seq, poll_s)
        now = clock()
        if frame is None:
            if now - last_frame > idle_s:
                return
            continue
        seq = frame.seq
        last_frame = now
        yield mjpeg_part(frame.jpeg)
        if period:
            await asyncio.sleep(period)
