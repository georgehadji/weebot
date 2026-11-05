"""H20b: the effect ledger proves whether checks ran after the last edit."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.unit.test_session_security_state_durable import MemoryStore
from tests.unit.test_tool_executor_egress import FakeToolCollection, make_guard
from weebot.application.agents.executor._session_scope import get_session_scope
from weebot.application.agents.executor._tool_executor import ToolExecutor
from weebot.application.flows.states.verifying import VerifyingState
from weebot.application.services.effect_ledger import EffectLedger
from weebot.application.services.verification_evidence import (
    classify_verification_command as classify,
)
from weebot.application.services.verification_evidence import commands_run, evidence_status
from weebot.core.background_tasks import get_background_tasks
from weebot.domain.models.tool_result import ToolResult

SESSION = "sess-evidence"


@pytest.fixture(autouse=True)
def clean():
    get_session_scope().close(SESSION)
    yield
    get_session_scope().close(SESSION)


def _executor(store, result: ToolResult | None = None) -> ToolExecutor:
    ex = ToolExecutor(
        tools=FakeToolCollection(result=result),
        egress_guard=make_guard(),
        effect_ledger=EffectLedger(store),
    )
    ex.set_step_context("step-1", SESSION, "do it")
    return ex


async def _status(store):
    await get_background_tasks().drain()
    flow = SimpleNamespace(_event_store=store, _session=SimpleNamespace(id=SESSION))
    return await VerifyingState()._gate_evidence(flow)


@pytest.mark.parametrize(
    "command,kind",
    [
        ("pytest tests/ -q", "pytest"),
        ("python -m pytest -x", "pytest"),
        ("cd app && npm test", "npm_test"),
        ("npm run build", "npm_build"),
        ("make check", "make"),
        ("ruff check .", "ruff"),
        ("npx tsc --noEmit", "tsc"),
        ("cargo test --all", "cargo_test"),
        ("go test ./...", "go_test"),
        ("dotnet test", "dotnet_test"),
        ("mvn -q test", "mvn_test"),
        ("echo pytest", None),
        ("git status", None),
        ("pip install pytest-cov", None),
    ],
)
def test_classifier(command, kind):
    assert classify(command) == kind


def test_a_failing_run_is_never_evidence():
    rows = [{"kind": "code_written"}, {"kind": "verification_ran", "ok": False}]
    assert evidence_status(rows) == "stale_after_edit"
    assert evidence_status([]) is None


@pytest.mark.asyncio
async def test_edit_then_test_is_verified():
    store = MemoryStore()
    ex = _executor(store)
    await ex.execute_tool("file_editor", {"command": "create", "path": "a.py", "file_text": "x"})
    await ex.execute_tool("bash", {"command": "pytest -q"})

    status, commands = await _status(store)

    assert status == "verified"
    assert commands == ["pytest -q (passed)"]


@pytest.mark.asyncio
async def test_test_then_edit_is_stale():
    store = MemoryStore()
    ex = _executor(store)
    await ex.execute_tool("bash", {"command": "pytest -q"})
    await ex.execute_tool("file_editor", {"command": "str_replace", "path": "a.py"})

    status, _ = await _status(store)

    assert status == "stale_after_edit"


@pytest.mark.asyncio
async def test_a_failed_test_run_is_recorded_as_failed():
    store = MemoryStore()
    ex = _executor(store, ToolResult(output="", error="Exit code 1"))
    await ex.execute_tool("bash", {"command": "pytest -q"})
    await get_background_tasks().drain()

    rows = [r["data"] for r in store.rows if r["event_type"] == "session_flag"]

    assert commands_run(rows) == ["pytest -q (failed)"]


@pytest.mark.asyncio
async def test_a_non_source_edit_and_a_view_leave_no_edit_row():
    store = MemoryStore()
    ex = _executor(store)
    await ex.execute_tool("file_editor", {"command": "create", "path": "notes.md"})
    await ex.execute_tool("file_editor", {"command": "view", "path": "a.py"})

    status, _ = await _status(store)

    assert status is None
