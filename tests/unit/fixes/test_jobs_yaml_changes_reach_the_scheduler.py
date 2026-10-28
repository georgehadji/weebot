"""Editing config/jobs.yaml changes the persisted jobs.

Found by the dead-code audit: ``load_from_config`` created only jobs it had not seen,
so turning a job off, changing its interval, or removing it in jobs.yaml never reached
the jobs table; ``skill_promotion_check`` stayed in every existing database after its
yaml entry was deleted.
"""

from __future__ import annotations

import textwrap

from weebot.scheduling.scheduler import SchedulingManager

_V1 = """
jobs:
  - job_id: sweep
    name: "Sweep"
    trigger_type: "interval"
    trigger_config:
      hours: 1
    callable_name: "sweep"
    enabled: true
"""

_V2 = """
jobs:
  - job_id: sweep
    name: "Sweep"
    trigger_type: "interval"
    trigger_config:
      minutes: 5
    callable_name: "sweep"
    enabled: false
"""

_V3 = """
retired_jobs:
  - sweep
jobs: []
"""


def _write(path, text):
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


async def test_a_changed_entry_updates_the_stored_job(tmp_path):
    manager = SchedulingManager(db_path=tmp_path / "jobs.db")
    cfg = tmp_path / "jobs.yaml"
    await manager.load_from_config(_write(cfg, _V1))
    created = manager.get_job("sweep").created_at

    await manager.load_from_config(_write(cfg, _V2))
    job = manager.get_job("sweep")
    assert not job.enabled
    assert job.trigger_config == {"minutes": 5}
    assert job.created_at == created  # updated in place, not recreated


async def test_a_retired_entry_is_deleted_and_other_jobs_stay(tmp_path):
    manager = SchedulingManager(db_path=tmp_path / "jobs.db")
    cfg = tmp_path / "jobs.yaml"
    await manager.load_from_config(_write(cfg, _V1))
    await manager.create_job(
        job_id="made_in_code", name="x", trigger_type="interval",
        trigger_config={"hours": 1}, callable_name="x",
    )

    await manager.load_from_config(_write(cfg, _V3))
    assert manager.get_job("sweep") is None
    assert manager.get_job("made_in_code") is not None


async def test_the_shipped_yaml_retires_skill_promotion_check():
    import yaml

    from weebot.scheduling import scheduler

    path = scheduler.Path(scheduler.__file__).resolve().parent.parent / "config" / "jobs.yaml"
    assert "skill_promotion_check" in yaml.safe_load(path.read_text())["retired_jobs"]
