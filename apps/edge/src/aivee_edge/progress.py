"""Progress of an offline clip run, written as a small JSON file the API polls.

`{"frames": 120, "position_s": 11.9, "duration_s": 95.0, "done": false}`; written atomically
(temp file + rename), at most every `every_s` seconds of wall time and once more at the end.
"""

import json
import os
import time
from pathlib import Path

from aivee_edge.domain.ports import FrameSource, Image


class ProgressSource:
    """Wraps a FrameSource and records how far into the clip it has read."""

    def __init__(
        self,
        inner: FrameSource,
        path: str | Path,
        *,
        duration_s: float | None,
        every_s: float = 0.5,
    ) -> None:
        self._inner = inner
        self._path = Path(path)
        self._duration_s = duration_s
        self._every_s = every_s
        self._frames = 0
        self._position_s = 0.0
        self._written_at = -float("inf")

    def read(self) -> tuple[float, Image] | None:
        item = self._inner.read()
        if item is None:
            self._write(done=True)
            return None
        self._frames += 1
        self._position_s = item[0]
        now = time.monotonic()
        if now - self._written_at >= self._every_s:
            self._written_at = now
            self._write(done=False)
        return item

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if callable(close):
            close()

    def _write(self, *, done: bool) -> None:
        data = {
            "frames": self._frames,
            "position_s": round(self._position_s, 3),
            "duration_s": self._duration_s,
            "done": done,
        }
        tmp = self._path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, self._path)
