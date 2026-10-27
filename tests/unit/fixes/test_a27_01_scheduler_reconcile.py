"""A01: jobs persisted in jobs.db must be scheduled again after a restart.

APScheduler here uses a memory job store, and `start()` used to run only the
catch-up pass, so a restarted process had rows but nothing scheduled.
"""

from __future__ import annotations


from weebot.scheduling.scheduler import SchedulingManager


async def _restart(db_path) -> SchedulingManager:
    manager = SchedulingManager(db_path)
    await manager.start()
    return manager


async def test_a_persisted_job_is_scheduled_after_a_restart(tmp_path):
    db = tmp_path / "jobs.db"
    first = SchedulingManager(db)
    await first.create_job(
        job_id="j1", name="J", trigger_type="interval",
        trigger_config={"hours": 1}, callable_name="noop",
    )
    second = await _restart(db)
    try:
        assert second.scheduler.get_job("j1") is not None
    finally:
        await second.stop()


async def test_a_disabled_job_is_not_scheduled_after_a_restart(tmp_path):
    db = tmp_path / "jobs.db"
    first = SchedulingManager(db)
    await first.create_job(
        job_id="off", name="Off", trigger_type="interval",
        trigger_config={"hours": 1}, callable_name="noop", enabled=False,
    )
    second = await _restart(db)
    try:
        assert second.scheduler.get_job("off") is None
    finally:
        await second.stop()


async def test_a_paused_job_is_not_scheduled_until_resumed(tmp_path):
    db = tmp_path / "jobs.db"
    first = SchedulingManager(db)
    await first.create_job(
        job_id="p", name="P", trigger_type="interval",
        trigger_config={"hours": 1}, callable_name="noop",
    )
    await first.pause_job("p")
    second = await _restart(db)
    try:
        assert second.scheduler.get_job("p") is None
        await second.resume_job("p")
        assert second.scheduler.get_job("p") is not None
    finally:
        await second.stop()


async def test_one_bad_trigger_does_not_stop_the_others(tmp_path):
    db = tmp_path / "jobs.db"
    first = SchedulingManager(db)
    await first.create_job(
        job_id="good", name="G", trigger_type="interval",
        trigger_config={"hours": 1}, callable_name="noop",
    )
    await first.create_job(
        job_id="bad", name="B", trigger_type="interval",
        trigger_config={"hours": 1}, callable_name="noop",
    )
    first.scheduler.remove_job("bad")
    # Corrupt the stored trigger the way a hand-edited row would be.
    import sqlite3
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE jobs SET trigger_type = 'nonsense' WHERE job_id = 'bad'")
    second = await _restart(db)
    try:
        assert second.scheduler.get_job("good") is not None
        assert second.scheduler.get_job("bad") is None
    finally:
        await second.stop()


async def test_reconcile_twice_keeps_one_scheduler_job(tmp_path):
    manager = SchedulingManager(tmp_path / "jobs.db")
    await manager.create_job(
        job_id="j", name="J", trigger_type="interval",
        trigger_config={"hours": 1}, callable_name="noop",
    )
    await manager.start()
    try:
        await manager.reconcile()
        assert [j.id for j in manager.scheduler.get_jobs()] == ["j"]
    finally:
        await manager.stop()
