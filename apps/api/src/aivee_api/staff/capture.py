"""Guided enrolment from a live camera: "Adaugă angajat în 20 de secunde".

The employee stands in front of a cloud camera and turns slowly; the API samples the newest
frames the connector posts (`aivee_api.frames.store`), keeps only the largest person in each
(guests in the background would pollute the profile), and holds the crops in memory under a
short-lived token. The dashboard shows the thumbnails, the owner unticks bad ones and
confirms; only then are the crops embedded and added to a profile.

In memory, single replica, like the live frames themselves. Nothing is written to disk.
"""

import secrets
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from aivee_api.frames.store import LiveFrames
from aivee_api.staff.enrol import Enroller

CAPTURE_MIN_S = 5
CAPTURE_MAX_S = 30
CAPTURE_DEFAULT_S = 20
SAMPLE_INTERVAL_S = 1.5
CAPTURE_TTL_S = 600.0
MAX_CAPTURES = 16
THUMB_MAX_SIDE = 240

Sleep = Callable[[float], Awaitable[None]]


async def sample_frames(
    frames: LiveFrames, camera_id: str, seconds: float, interval_s: float, sleep: Sleep
) -> list[bytes]:
    """The camera's newest JPEG once every `interval_s` for `seconds`, skipping a frame
    already taken (the connector posts slower than we sample)."""
    out: list[bytes] = []
    last_seq = -1
    ticks = max(1, int(seconds / interval_s))
    for tick in range(ticks):
        frame = frames.latest(camera_id)
        if frame is not None and frame.seq != last_seq:
            out.append(frame.jpeg)
            last_seq = frame.seq
        if tick < ticks - 1:
            await sleep(interval_s)
    return out


def capture_candidates(enroller: Enroller, jpegs: Sequence[bytes]) -> tuple[list[Any], list[bytes]]:
    """The largest person of each frame and a small JPEG of it. CPU-bound."""
    crops: list[Any] = []
    thumbs: list[bytes] = []
    for jpeg in jpegs:
        crop = enroller.largest_person(jpeg)
        if crop is None:
            continue
        crops.append(crop)
        thumbs.append(enroller.thumbnail(crop, THUMB_MAX_SIDE))
    return crops, thumbs


@dataclass(frozen=True)
class Capture:
    user_id: str
    camera_id: str
    location_id: str
    crops: list[Any]
    at: float


class CaptureStore:
    """Captures awaiting confirmation, by token; only the user who took one can use it."""

    def __init__(
        self,
        *,
        ttl_s: float = CAPTURE_TTL_S,
        max_items: int = MAX_CAPTURES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_s = ttl_s
        self._max = max_items
        self._clock = clock
        self._items: OrderedDict[str, Capture] = OrderedDict()

    def __len__(self) -> int:
        return len(self._items)

    def _purge(self) -> None:
        now = self._clock()
        for token in [t for t, c in self._items.items() if now - c.at > self._ttl_s]:
            del self._items[token]
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def put(self, user_id: str, camera_id: str, location_id: str, crops: list[Any]) -> str:
        token = secrets.token_urlsafe(16)
        self._items[token] = Capture(user_id, camera_id, location_id, crops, self._clock())
        self._purge()
        return token

    def get(self, token: str, user_id: str) -> Capture | None:
        self._purge()
        capture = self._items.get(token)
        return capture if capture is not None and capture.user_id == user_id else None

    def drop(self, token: str) -> None:
        self._items.pop(token, None)
