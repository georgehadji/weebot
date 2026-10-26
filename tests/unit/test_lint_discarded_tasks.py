"""CON-1: no fire-and-forget task is left unowned, and the gate proves it can fail.

Plan item 1.3 of tasks/specs/arch_audit_2026_10_remediation_plan.md. The gate is
`scripts/lint_unawaited_coroutines.py`; a gate nobody has watched fail is not a
gate, so most of this file feeds it code that must be flagged.
"""

from __future__ import annotations

import asyncio
import gc
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "lint_unawaited_coroutines.py"


def _run_gate(tmp_path: pathlib.Path, source: str) -> subprocess.CompletedProcess:
    pkg = tmp_path / "weebot"
    pkg.mkdir()
    (pkg / "mod.py").write_text(source, encoding="utf-8")
    (tmp_path / "cli").mkdir()
    return subprocess.run(
        [sys.executable, str(_SCRIPT)], cwd=tmp_path, capture_output=True, text=True
    )


class TestTheGate:
    @pytest.mark.parametrize(
        "statement",
        [
            "asyncio.create_task(work())",
            "asyncio.ensure_future(work())",
            "loop.create_task(work())",
            "_loop.create_task(work())",
            "ensure_future(work())",
        ],
    )
    def test_a_discarded_task_fails_the_gate(self, tmp_path, statement):
        result = _run_gate(
            tmp_path,
            f"import asyncio\nasync def work(): ...\nasync def go(loop, _loop):\n    {statement}\n",
        )
        assert result.returncode == 1, result.stdout
        assert "result discarded" in result.stdout

    @pytest.mark.parametrize(
        "statement",
        [
            "task = asyncio.create_task(work())",  # held
            "await asyncio.create_task(work())",  # awaited
            "tg.create_task(work())",  # owned by the task group
            "get_background_tasks().spawn(work(), name='x')",  # the owner
        ],
    )
    def test_an_owned_task_passes(self, tmp_path, statement):
        result = _run_gate(
            tmp_path,
            "import asyncio\nasync def work(): ...\n"
            f"async def go(tg, get_background_tasks):\n    {statement}\n",
        )
        assert result.returncode == 0, result.stdout

    def test_the_tree_has_none(self):
        result = subprocess.run(
            [sys.executable, str(_SCRIPT)], cwd=_ROOT, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stdout


class TestSpawn:
    @pytest.mark.asyncio
    async def test_a_failing_task_is_logged_not_left_to_the_loop(self, caplog):
        from weebot.core.background_tasks import BackgroundTasks

        owner = BackgroundTasks()

        async def boom():
            raise RuntimeError("webhook reply failed")

        with caplog.at_level("WARNING"):
            owner.spawn(boom(), name="demo-boom")
            await owner.drain()
        assert "Background task demo-boom failed" in caplog.text

    @pytest.mark.asyncio
    async def test_a_task_survives_gc_and_completes(self):
        from weebot.core.background_tasks import BackgroundTasks

        owner = BackgroundTasks()
        done = asyncio.Event()

        async def reply():
            await asyncio.sleep(0.01)
            done.set()

        owner.spawn(reply(), name="demo-reply")
        gc.collect()
        await asyncio.wait_for(done.wait(), timeout=2)

    def test_the_old_import_path_is_the_same_object(self):
        from weebot.application.services import background_tasks as old
        from weebot.core import background_tasks as new

        assert old.BackgroundTasks is new.BackgroundTasks
        assert old.get_background_tasks is new.get_background_tasks


class TestTheSitesUseTheOwner:
    @pytest.mark.parametrize(
        "path",
        [
            "weebot/interfaces/web/routers/slack_webhook.py",
            "weebot/interfaces/web/routers/whatsapp_webhook.py",
            "weebot/application/flows/flow_router.py",
            "weebot/core/activity_stream.py",
            "weebot/infrastructure/notifications/telegram_adapter.py",
            "weebot/infrastructure/notifications/_base.py",
            "weebot/tools/bash_tool.py",
        ],
    )
    def test_the_site_spawns_through_the_owner(self, path):
        assert "get_background_tasks" in (_ROOT / path).read_text(encoding="utf-8")

    def test_the_web_lifespan_drains_before_the_pools_close(self):
        source = (_ROOT / "weebot/interfaces/web/main.py").read_text(encoding="utf-8")
        assert source.index("get_background_tasks().drain()") < source.index(
            "close_mcp_toolkit()"
        )
