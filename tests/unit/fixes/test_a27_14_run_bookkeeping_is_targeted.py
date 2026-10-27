"""A14: _execute_job saved its start-of-run snapshot over the whole row when the run ended,
undoing a pause, an edit or a delete made while the job was running."""

from __future__ import annotations

from weebot.scheduling.scheduler import JobStatus, SchedulingManager


async def _manager(tmp_path, action):
    manager = SchedulingManager(tmp_path / "jobs.db")

    async def job():
        await action(manager)

    manager.register_callable("work", job)
    await manager.create_job(
        job_id="j", name="Original", trigger_type="interval",
        trigger_config={"hours": 1}, callable_name="work",
    )
    return manager


async def test_a_pause_made_during_the_run_survives_it(tmp_path):
    manager = await _manager(tmp_path, lambda m: m.pause_job("j"))
    await manager._execute_job("j")
    assert manager.get_job("j").status == JobStatus.PAUSED.value


async def test_an_edit_made_during_the_run_survives_it(tmp_path):
    manager = await _manager(tmp_path, lambda m: m.update_job("j", name="Renamed"))
    await manager._execute_job("j")
    assert manager.get_job("j").name == "Renamed"


async def test_a_delete_made_during_the_run_is_not_undone(tmp_path):
    manager = await _manager(tmp_path, lambda m: m.delete_job("j"))
    await manager._execute_job("j")
    assert manager.get_job("j") is None


async def test_a_normal_run_still_records_its_outcome(tmp_path):
    async def nothing(_m):
        return None

    manager = await _manager(tmp_path, nothing)
    await manager._execute_job("j")
    job = manager.get_job("j")
    assert (job.status, job.run_count, job.error_count) == (JobStatus.COMPLETED.value, 1, 0)
    assert job.last_run is not None


async def test_a_failing_run_records_the_error(tmp_path):
    async def boom(_m):
        raise RuntimeError("nope")

    manager = await _manager(tmp_path, boom)
    await manager._execute_job("j")
    job = manager.get_job("j")
    assert (job.status, job.run_count, job.error_count) == (JobStatus.FAILED.value, 0, 1)
    assert job.last_error == "nope"
