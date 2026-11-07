"""Login rate limit: at most N failed attempts per email in a sliding window.

In-process (the API runs as one process); a restart forgets the counters, which is acceptable
for a brute-force brake. Single event loop only.
"""

from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta


def _now() -> datetime:
    return datetime.now(UTC)


def normalise_email(email: str) -> str:
    return email.strip().lower()


class LoginRateLimiter:
    def __init__(
        self,
        max_failures: int = 10,
        window: timedelta = timedelta(minutes=15),
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._max = max_failures
        self._window = window
        self._clock = clock
        self._failures: dict[str, deque[datetime]] = {}

    def _recent(self, email: str) -> deque[datetime]:
        key = normalise_email(email)
        q = self._failures.setdefault(key, deque())
        cutoff = self._clock() - self._window
        while q and q[0] <= cutoff:
            q.popleft()
        if not q:
            del self._failures[key]
            return deque()
        return q

    def blocked(self, email: str) -> bool:
        return len(self._recent(email)) >= self._max

    def failed(self, email: str) -> None:
        self._recent(email)
        self._failures.setdefault(normalise_email(email), deque()).append(self._clock())
