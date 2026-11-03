"""The per-step tool-call cap: 24 rounds, shared by the guard and the executor.

It used to be 12, hardcoded twice. A step doing real work (read, edit, run, verify)
routinely needs more than twelve rounds, and the old cap ended those steps with a summary
whose fallback text was "Step completed (budget cap)." — work reported as done while it
was not. The literal is gone; this pins the constant and the wiring that reads it.
"""

from __future__ import annotations

from pathlib import Path

from weebot.application.agents.executor._iteration_guard import (
    DEFAULT_MAX_TOOL_CALLS_PER_STEP,
    IterationGuard,
)


def test_the_cap_allows_the_full_default_rounds_then_stops():
    guard = IterationGuard(step_id="s1")

    for _ in range(DEFAULT_MAX_TOOL_CALLS_PER_STEP):
        guard.record_loop_turn()
        assert not guard.is_tool_call_budget_exhausted()

    guard.record_loop_turn()

    assert guard.is_tool_call_budget_exhausted()


def test_the_default_cap_is_at_least_24():
    # 12 ended ordinary steps mid-work; lowering it again should be a deliberate edit.
    assert DEFAULT_MAX_TOOL_CALLS_PER_STEP >= 24


def test_the_executor_takes_its_limits_from_the_shared_config_not_literals():
    src = Path("weebot/application/agents/executor/_base.py").read_text(encoding="utf-8")
    assert "IterationGuard(step.id, self._guard_config)" in src
    assert "max_tool_calls_per_step=12" not in src
    assert "repeated_tool_signature_limit=4" not in src
