"""F7: a scheduled job that is cancelled must record its end.

`outcome` was bound only on success or in `except Exception`. A cancel raises
`CancelledError`, a `BaseException`, so the `finally` read an unbound local: the
`UnboundLocalError` replaced the cancel and the row stayed `running` for good.
"""

from __future__ import annotations

import asyncio

import pytest

from weebot.scheduling.scheduler import JobStatus, SchedulingManager


async def _start_blocked_job(tmp_path):
    manager = SchedulingManager(tmp_path / "jobs.db")
    started = asyncio.Event()

    async def job():
        started.set()
        await asyncio.Event().wait()

    manager.register_callable("work", job)
    await manager.create_job(
        job_id="j", name="Blocked", trigger_type="interval",
        trigger_config={"hours": 1}, callable_name="work",
    )
    task = asyncio.create_task(manager._execute_job("j"))
    await asyncio.wait_for(started.wait(), timeout=5)
    return manager, task


async def test_a_cancelled_job_is_not_left_running(tmp_path):
    manager, task = await _start_blocked_job(tmp_path)
    assert manager.get_job("j").status == JobStatus.RUNNING.value

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    job = manager.get_job("j")
    assert job.status == JobStatus.FAILED.value
    assert (job.run_count, job.error_count) == (0, 1)
    assert job.last_error == "cancelled"


async def test_the_cancel_propagates_and_the_job_can_run_again(tmp_path):
    manager, task = await _start_blocked_job(tmp_path)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert "j" not in manager._running_jobs
