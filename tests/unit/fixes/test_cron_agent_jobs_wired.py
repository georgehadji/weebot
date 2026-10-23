"""Cron agent jobs saved by `cron-agent create` actually run on schedule.

Three breaks, any one enough (found 2026-10-23, W5.3's last non-root site):
- nothing called `SchedulingManager.load_cron_agent_jobs`, so the web server's
  scheduler never loaded `~/.weebot/cron_jobs.json`;
- the loader registered one callable that takes `job_id`, and the scheduler
  calls a job's callable with no arguments: TypeError on every run;
- the runner got `tool_registry=None`, so a job had no tools.
The loader also built its own Container(); it now uses the caller's.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from weebot.scheduling.scheduler import SchedulingManager


class _Container:
    def __init__(self):
        self.registry = object()

    def get(self, key):
        from weebot.application.ports.llm_port import LLMPort
        from weebot.application.ports.state_repo_port import StateRepositoryPort

        return {
            LLMPort: "llm",
            StateRepositoryPort: "repo",
            "create_flow": "flow-factory",
            "tool_registry": self.registry,
        }[key]


@pytest.mark.asyncio
async def test_a_saved_job_is_scheduled_and_its_callable_runs(tmp_path, monkeypatch):
    jobs = tmp_path / "cron_jobs.json"
    jobs.write_text(
        json.dumps(
            {"j1": {"id": "j1", "name": "daily", "prompt": "summarise news",
                    "schedule": "0 9 * * *", "enabled": True}}
        ),
        encoding="utf-8",
    )
    ran = {}

    class _Runner:
        def __init__(self, **kw):
            ran["kw"] = kw

        async def run(self, job):
            ran["prompt"] = job.prompt
            return "ok"

    class _Delivery:
        async def deliver(self, job, result):
            ran["delivered"] = result

    monkeypatch.setattr(
        "weebot.application.services.cron_agent_runner.CronAgentRunner", _Runner
    )
    monkeypatch.setattr(
        "weebot.application.services.cron_delivery_service.CronDeliveryService", _Delivery
    )
    container = _Container()
    scheduler = SchedulingManager(db_path=tmp_path / "jobs.db")

    assert await scheduler.load_cron_agent_jobs(jobs_path=jobs, container=container) == 1
    job = scheduler.get_job("j1")
    func = scheduler._callables[job.callable_name]
    await func()  # how the scheduler calls it: no arguments

    assert ran["prompt"] == "summarise news" and ran["delivered"] == "ok"
    assert ran["kw"]["tool_registry"] is container.registry


@pytest.mark.asyncio
async def test_without_a_container_nothing_is_loaded(tmp_path):
    jobs = tmp_path / "cron_jobs.json"
    jobs.write_text(json.dumps({"j1": {"schedule": "0 9 * * *"}}), encoding="utf-8")
    scheduler = SchedulingManager(db_path=tmp_path / "jobs.db")
    assert await scheduler.load_cron_agent_jobs(jobs_path=jobs) == 0


def test_the_web_server_loads_cron_agent_jobs():
    root = pathlib.Path(__file__).resolve().parents[3]
    source = (root / "weebot/interfaces/web/main.py").read_text(encoding="utf-8")
    assert "load_cron_agent_jobs(container=container)" in source
