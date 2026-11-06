"""In-process fan-out of live detections from the MQTT link to every /ws/events socket.

Live boxes are only worth showing while fresh, so each socket gets a small bounded queue and
a slow reader loses the oldest frames instead of growing memory. Single event loop only.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

from aivee_api.events.schemas import DetectionsMessage


class LiveDetections:
    def __init__(self, maxsize: int = 10) -> None:
        self._maxsize = maxsize
        self._queues: set[asyncio.Queue[DetectionsMessage]] = set()

    @property
    def subscribers(self) -> int:
        return len(self._queues)

    @contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue[DetectionsMessage]]:
        queue: asyncio.Queue[DetectionsMessage] = asyncio.Queue(self._maxsize)
        self._queues.add(queue)
        try:
            yield queue
        finally:
            self._queues.discard(queue)

    def publish(self, message: DetectionsMessage) -> None:
        for queue in self._queues:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(message)
