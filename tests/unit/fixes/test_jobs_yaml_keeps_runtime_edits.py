"""A job changed at runtime keeps the change across restarts, until jobs.yaml changes.

Found by review of the yaml-sync fix: ``load_from_config`` wrote every yaml field into
the stored row on each startup, so a job the agent disabled through ``schedule_tool``
(``update_job``) was enabled again by the next restart.
"""

from __future__ import annotations

import textwrap

from weebot.scheduling.scheduler import SchedulingManager

_ON = """
jobs:
  - job_id: sweep
    name: "Sweep"
    trigger_type: "interval"
    trigger_config:
      hours: 1
    callable_name: "sweep"
    enabled: true
"""

_ON_EVERY_2H = _ON.replace("hours: 1", "hours: 2")


def _write(path, text):
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


async def test_a_restart_keeps_a_job_disabled_at_runtime(tmp_path):
    manager = SchedulingManager(db_path=tmp_path / "jobs.db")
    cfg = _write(tmp_path / "jobs.yaml", _ON)
    await manager.load_from_config(cfg)
    await manager.update_job("sweep", enabled=False)

    assert await manager.load_from_config(cfg) == 0
    assert not manager.get_job("sweep").enabled


async def test_a_later_yaml_edit_still_applies_and_keeps_the_runtime_edit(tmp_path):
    manager = SchedulingManager(db_path=tmp_path / "jobs.db")
    cfg = _write(tmp_path / "jobs.yaml", _ON)
    await manager.load_from_config(cfg)
    await manager.update_job("sweep", enabled=False)

    await manager.load_from_config(_write(cfg, _ON_EVERY_2H))
    job = manager.get_job("sweep")
    assert job.trigger_config == {"hours": 2}
    assert not job.enabled
