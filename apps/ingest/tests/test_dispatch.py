"""R3: the notification dispatcher and the retrying channel wrapper."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from aivee_api.push.sender import PushKind
from aivee_contracts.events import AlertEvent
from aivee_ingest.dispatch import NotifyDispatcher, RetryingNotifier

EVENT = AlertEvent(
    event_id="e1",
    rule_id="r1",
    camera_id="cam1",
    zone_id="t1",
    state="opened",
    at=datetime(2026, 11, 6, 12, 30, tzinfo=UTC),
    summary_ro="Masa 1 așteaptă",
)


async def test_jobs_of_one_alert_run_in_order_while_another_alert_is_stuck() -> None:
    d = NotifyDispatcher(workers=4)
    stuck = asyncio.Event()
    done: list[str] = []

    async def hang() -> None:
        await stuck.wait()

    def record(name: str) -> object:
        async def job() -> None:
            await asyncio.sleep(0)
            done.append(name)

        return job

    # crc32: "stuck-alert" and "a1" land on different workers of four.
    d.submit("stuck-alert", "hang", hang)
    for i in range(5):
        d.submit("a1", f"a1-{i}", record(f"a1-{i}"))  # type: ignore[arg-type]
    await asyncio.wait_for(_until(lambda: len(done) == 5), 2)
    assert done == [f"a1-{i}" for i in range(5)]
    stuck.set()
    await d.drain()
    await d.aclose()


async def _until(cond: object) -> None:
    while not cond():  # type: ignore[operator]
        await asyncio.sleep(0.01)


async def test_a_full_queue_drops_without_blocking(caplog: pytest.LogCaptureFixture) -> None:
    d = NotifyDispatcher(workers=1, queue_size=2)
    gate = asyncio.Event()

    async def wait() -> None:
        await gate.wait()

    assert d.submit("a", "1", wait)
    await asyncio.sleep(0)  # the worker takes job 1
    assert d.submit("a", "2", wait) and d.submit("a", "3", wait)
    assert not d.submit("a", "4", wait)
    assert "notify_dropped reason=queue_full job=4 alert=a" in caplog.text
    gate.set()
    await d.drain()
    await d.aclose()


async def test_a_failing_job_is_logged_and_the_next_one_runs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    d = NotifyDispatcher(workers=1)
    ran: list[str] = []

    async def boom() -> None:
        raise RuntimeError("telegram down")

    async def ok() -> None:
        ran.append("ok")

    d.submit("a", "boom", boom)
    d.submit("a", "ok", ok)
    await d.drain()
    assert ran == ["ok"] and "notify job boom failed" in caplog.text
    await d.aclose()


async def test_submit_later_runs_after_the_delay_without_holding_a_worker() -> None:
    d = NotifyDispatcher(workers=1)
    ran: list[str] = []

    async def job(name: str) -> None:
        ran.append(name)

    d.submit_later(0.2, "a", "late", lambda: job("late"))
    d.submit("a", "now", lambda: job("now"))
    await asyncio.sleep(0.05)
    assert ran == ["now"]
    await d.drain()
    assert ran == ["now", "late"]
    await d.aclose()


class Flaky:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def notify(self, event: AlertEvent, snapshot: Path | None) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("Telegram API error 502")

    async def send_text(
        self, text: str, tag: str | None = None, *, title: str | None = None, kind: PushKind
    ) -> None:
        await self.notify(EVENT, None)


async def test_retrying_notifier_retries_with_backoff_then_succeeds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    inner = Flaky(failures=2)
    await RetryingNotifier(inner, attempts=3, base_delay_s=0.01).notify(EVENT, None)
    assert inner.calls == 3
    assert caplog.text.count("notify_retry channel=Flaky") == 2


async def test_retrying_notifier_gives_up_after_its_attempts() -> None:
    inner = Flaky(failures=5)
    with pytest.raises(RuntimeError):
        await RetryingNotifier(inner, attempts=2, base_delay_s=0.01).send_text("x", kind="device")
    assert inner.calls == 2


async def test_retrying_notifier_skips_lifecycle_calls_its_channel_lacks() -> None:
    inner = Flaky(failures=0)
    wrapped = RetryingNotifier(inner)
    await wrapped.alert_resolved(None, "✅")  # type: ignore[arg-type]
    assert inner.calls == 0
