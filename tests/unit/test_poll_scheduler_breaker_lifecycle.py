"""Lifecycle bugs in the polling gateways, the scheduler and the circuit breaker.

- A polling gateway's stop() before start() raised AttributeError, and a second start()
  orphaned the first poll loop. Email polled a failing mailbox at a fixed interval.
- Scheduler pause/resume rewrote the whole row from a snapshot, and resume set PENDING on a
  job that was running. The schedule tool had its own SchedulingManager beside the app's.
- A HALF_OPEN circuit breaker let every caller through instead of one probe.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from weebot.core.circuit_breaker import BreakerState, CircuitBreaker
from weebot.interfaces.gateways.email import EmailAdapter
from weebot.interfaces.gateways.signal import SignalAdapter
from weebot.scheduling.scheduler import JobStatus, SchedulingManager, process_scheduler
from weebot.tools.schedule_tool import get_scheduler

# --- polling gateways --------------------------------------------------------------------


def _signal() -> SignalAdapter:
    return SignalAdapter(
        rest_url="http://x", account_number="+1", state_repo=MagicMock(), llm=MagicMock()
    )


async def test_stop_before_start_is_harmless():
    await _signal().stop()


async def test_a_second_start_does_not_start_a_second_loop():
    adapter = _signal()
    runs = 0
    gate = asyncio.Event()

    async def _loop():
        nonlocal runs
        runs += 1
        await gate.wait()

    adapter._poll_loop = _loop
    await adapter.start()
    await adapter.start()
    await asyncio.sleep(0)
    assert runs == 1
    await adapter.stop()
    await adapter.stop()  # twice is fine too
    assert adapter._poll_task is None


async def test_email_backs_off_on_a_failing_mailbox(monkeypatch):
    adapter = EmailAdapter(state_repo=MagicMock(), llm=MagicMock(), poll_interval_seconds=1.0)
    adapter._running = True

    async def _fail():
        raise OSError("imap down")

    adapter.receive_messages = _fail
    slept: list[float] = []

    async def _sleep(delay):
        slept.append(delay)
        if len(slept) >= 10:
            adapter._running = False

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    await adapter._poll_loop()
    assert min(slept) >= 1.0  # never below the configured interval
    assert slept[-1] > 5 * slept[0]  # grows instead of staying fixed


# --- scheduler ---------------------------------------------------------------------------


@pytest.fixture
async def manager(tmp_path):
    mgr = SchedulingManager(db_path=tmp_path / "jobs.db")
    await mgr.create_job("j", "J", "interval", {"seconds": 3600}, command="echo hi")
    return mgr


async def test_pause_keeps_the_run_columns_a_run_wrote(manager):
    await manager._record_run_start("j", datetime.now(UTC))
    await manager.pause_job("j")
    await manager._record_run_end("j", ok=False, error="boom")
    job = manager.get_job("j")
    assert (job.status, job.error_count, job.last_error) == (JobStatus.PAUSED.value, 1, "boom")


async def test_resume_of_a_job_mid_run_says_running(manager):
    await manager.pause_job("j")
    manager._running_jobs.add("j")
    await manager.resume_job("j")
    assert manager.get_job("j").status == JobStatus.RUNNING.value


async def test_resume_leaves_a_job_that_is_not_paused_alone(manager):
    await manager._record_run_end("j", ok=True, error=None)
    await manager.resume_job("j")
    assert manager.get_job("j").status == JobStatus.COMPLETED.value


def test_the_schedule_tool_and_the_app_share_one_scheduler():
    from weebot.application.di import Container

    assert get_scheduler() is process_scheduler()
    container = Container()
    container.configure_defaults()
    assert container.build_scheduler() is process_scheduler()


# --- circuit breaker ---------------------------------------------------------------------


def _open_breaker() -> CircuitBreaker:
    return CircuitBreaker(
        failure_threshold=1, cooldown_seconds=0.05, jitter_percent=0, enable_stagger=False
    )


async def test_half_open_lets_one_probe_through():
    breaker = _open_breaker()
    await breaker.record_failure("m")
    time.sleep(0.06)
    first, second = await breaker.evaluate("m"), await breaker.evaluate("m")
    assert first.allowed and first.state == BreakerState.HALF_OPEN
    assert not second.allowed and second.reason == "Probe in flight"
    await breaker.record_success("m")
    assert (await breaker.evaluate("m")).state == BreakerState.CLOSED


async def test_a_probe_that_never_reports_does_not_wedge_the_breaker():
    breaker = _open_breaker()
    await breaker.record_failure("m")
    time.sleep(0.06)
    assert (await breaker.evaluate("m")).allowed  # the probe, which never reports back
    time.sleep(0.06)
    assert (await breaker.evaluate("m")).allowed
