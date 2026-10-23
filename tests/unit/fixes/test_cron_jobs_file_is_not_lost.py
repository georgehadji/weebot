"""An unreadable cron jobs file is set aside, not silently overwritten (F77).

`_load_jobs` returned {} on any parse error with no log, and the next
`cron create` saved over the file, losing every existing job.
"""

from __future__ import annotations

from cli.commands import cron_agent


def test_a_corrupt_jobs_file_is_kept(tmp_path, monkeypatch):
    path = tmp_path / "cron_jobs.json"
    path.write_text('{"job-1": {"name": "nightly"', encoding="utf-8")  # truncated JSON
    monkeypatch.setattr(cron_agent, "CRON_JOBS_PATH", path)

    assert cron_agent._load_jobs() == {}
    cron_agent._save_jobs({"job-2": {"name": "new"}})

    kept = [p for p in tmp_path.iterdir() if p.name.startswith("cron_jobs.json.corrupt")]
    assert len(kept) == 1 and '"nightly"' in kept[0].read_text(encoding="utf-8")
