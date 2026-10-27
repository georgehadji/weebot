"""A14 (json half): a finished cron agent run must update only its own record, from a fresh read."""

from __future__ import annotations

import json

from weebot.scheduling.scheduler import SchedulingManager

record = SchedulingManager._record_cron_agent_run


def test_other_jobs_added_during_the_run_are_kept(tmp_path):
    path = tmp_path / "cron_jobs.json"
    path.write_text(json.dumps({"a": {"run_count": 0}}))
    # A second process adds "b" while "a" is running...
    path.write_text(json.dumps({"a": {"run_count": 0}, "b": {"run_count": 7}}))
    record(path, "a", "done")
    saved = json.loads(path.read_text())
    assert saved["b"] == {"run_count": 7}
    assert (saved["a"]["run_count"], saved["a"]["last_result"]) == (1, "done")


def test_a_job_deleted_during_the_run_is_not_brought_back(tmp_path):
    path = tmp_path / "cron_jobs.json"
    path.write_text(json.dumps({"b": {}}))
    record(path, "a", "done")
    assert list(json.loads(path.read_text())) == ["b"]


def test_an_unreadable_file_is_left_alone(tmp_path):
    path = tmp_path / "cron_jobs.json"
    path.write_text("{not json")
    record(path, "a", "done")
    assert path.read_text() == "{not json"


def test_the_write_leaves_no_temp_file(tmp_path):
    path = tmp_path / "cron_jobs.json"
    path.write_text(json.dumps({"a": {}}))
    record(path, "a", "x" * 900)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["cron_jobs.json"]
    assert len(json.loads(path.read_text())["a"]["last_result"]) == 500
