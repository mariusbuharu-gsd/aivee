"""Notifications off the MQTT loop (R3): bounded queues, a few workers, retries with backoff.

The handler stores an event and returns; what it has to tell the staff (wait for the
snapshot, verify, send Telegram and Web Push, edit the message when the alert resolves)
becomes a job on `NotifyDispatcher`. Jobs with the same key (the alert id) always go to the
same worker, in submission order, so an alert's "opened" goes out before its "resolved".
A full queue drops the job and logs `notify_dropped`: ingest never waits for a notifier.

`RetryingNotifier` wraps one channel (Telegram, Web Push) so a failed send is retried with
backoff without sending the other channels twice.

Jobs live in memory: a restart loses the ones still queued (a DB outbox is R1, later).
"""

import asyncio
import logging
import zlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar

from aivee_api.alerts.schemas import AlertView
from aivee_api.push.sender import PushKind
from aivee_contracts.events import AlertEvent

from aivee_ingest.notify import LifecycleNotifier, Notifier

log = logging.getLogger(__name__)

Job = Callable[[], Awaitable[object]]
T = TypeVar("T")


class NotifyDispatcher:
    def __init__(self, workers: int = 8, queue_size: int = 100) -> None:
        if workers < 1 or queue_size < 1:
            raise ValueError("workers and queue_size must be >= 1")
        self._queues: list[asyncio.Queue[tuple[str, Job]]] = [
            asyncio.Queue(maxsize=queue_size) for _ in range(workers)
        ]
        self._workers: list[asyncio.Task[None]] = []
        self._later: set[asyncio.Task[None]] = set()

    def submit(self, key: str | None, name: str, job: Job) -> bool:
        """Queue `job`; False (and logged) when its worker's queue is full. Never blocks."""
        self._start()
        queue = self._queues[zlib.crc32((key or "").encode()) % len(self._queues)]
        try:
            queue.put_nowait((name, job))
        except asyncio.QueueFull:
            log.error("notify_dropped reason=queue_full job=%s alert=%s", name, key)
            return False
        return True

    def submit_later(self, delay_s: float, key: str | None, name: str, job: Job) -> None:
        """`submit` after `delay_s`, without holding a worker meanwhile."""

        async def later() -> None:
            await asyncio.sleep(delay_s)
            self.submit(key, name, job)

        task = asyncio.create_task(later())
        self._later.add(task)
        task.add_done_callback(self._later.discard)

    def _start(self) -> None:
        if not self._workers:
            self._workers = [asyncio.create_task(self._work(q)) for q in self._queues]

    async def _work(self, queue: asyncio.Queue[tuple[str, Job]]) -> None:
        while True:
            name, job = await queue.get()
            try:
                await job()
            except Exception:
                log.exception("notify job %s failed", name)
            finally:
                queue.task_done()

    async def drain(self) -> None:
        """Wait until nothing is scheduled or queued (tests, shutdown)."""
        while True:
            if self._later:
                await asyncio.gather(*self._later, return_exceptions=True)
                continue
            for q in self._queues:
                await q.join()  # queued and in-flight jobs
            if not self._later:
                return

    async def aclose(self) -> None:
        for task in [*self._workers, *self._later]:
            task.cancel()
        await asyncio.gather(*self._workers, *self._later, return_exceptions=True)
        self._workers = []


class RetryingNotifier:
    """One channel with retries: `attempts` tries, waiting `base_delay_s`, doubling up to
    `max_delay_s`. The last failure is raised (CompositeNotifier logs it)."""

    def __init__(
        self,
        inner: Notifier,
        attempts: int = 3,
        base_delay_s: float = 1.0,
        max_delay_s: float = 10.0,
    ) -> None:
        self.inner = inner
        self._attempts = max(1, attempts)
        self._base = base_delay_s
        self._max = max_delay_s

    async def _retry(self, what: str, call: Callable[[], Awaitable[T]]) -> T:
        delay = self._base
        for attempt in range(1, self._attempts + 1):
            try:
                return await call()
            except Exception as e:
                if attempt == self._attempts:
                    raise
                log.warning(
                    "notify_retry channel=%s %s attempt=%d error=%s; again in %.1f s",
                    type(self.inner).__name__,
                    what,
                    attempt,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max)
        raise AssertionError("unreachable")

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        await self._retry(f"alert={event.event_id}", lambda: self.inner.notify(event, snapshot))

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None, kind: PushKind
    ) -> None:
        await self._retry(
            f"follow-up={tag}", lambda: self.inner.send_text(text, tag, title=title, kind=kind)
        )

    async def alert_resolved(self, view: AlertView, line: str) -> None:
        inner = self.inner
        if isinstance(inner, LifecycleNotifier):
            await self._retry(f"resolved={view.event_id}", lambda: inner.alert_resolved(view, line))

    async def alert_reminder(self, view: AlertView, text: str) -> None:
        inner = self.inner
        if isinstance(inner, LifecycleNotifier):
            await self._retry(f"reminder={view.event_id}", lambda: inner.alert_reminder(view, text))
