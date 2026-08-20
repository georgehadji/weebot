"""Tests for ExecutorAgent's session-constraint delivery (Phase 4).

Verifies the block lands as messages[-1] in the actual LLM call — the
paper's K_ub position — not merely that a setter exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock


from weebot.application.agents.executor import ExecutorAgent
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.plan import Plan, Step


@dataclass
class _FakeCascadeResponse:
    content: str = "done"
    tool_calls: list = field(default_factory=list)


def _make_executor(session_constraints=None) -> ExecutorAgent:
    executor = ExecutorAgent(
        llm=MagicMock(), tools=ToolCollection(), session_constraints=session_constraints
    )
    return executor


def _plan_and_step() -> tuple[Plan, Step]:
    step = Step(id="s1", description="do the thing")
    plan = Plan(title="t", message="m", steps=[step])
    return plan, step


class TestConstructorAndSetter:
    def test_constructor_kwarg_sets_block(self):
        executor = _make_executor(session_constraints="## SESSION CONSTRAINTS\n- x")
        assert executor._session_constraints_block == "## SESSION CONSTRAINTS\n- x"

    def test_none_by_default(self):
        executor = _make_executor()
        assert executor._session_constraints_block is None

    def test_empty_string_normalizes_to_none(self):
        executor = _make_executor(session_constraints="")
        assert executor._session_constraints_block is None

    def test_setter_mirrors_set_harness_block_shape(self):
        executor = _make_executor()
        executor.set_session_constraints("## SESSION CONSTRAINTS\n- y")
        assert executor._session_constraints_block == "## SESSION CONSTRAINTS\n- y"
        executor.set_session_constraints(None)
        assert executor._session_constraints_block is None


class TestDeliveryPosition:
    async def test_block_is_last_message_in_actual_llm_call(self, monkeypatch):
        """The real regression test: is it messages[-1] on the wire."""
        block = "## SESSION CONSTRAINTS\n  - never delete files"
        executor = _make_executor(session_constraints=block)

        captured: dict = {}

        async def _fake_call_with_cascade(messages, description):
            captured["messages"] = messages
            return _FakeCascadeResponse()

        executor._cascade.call_with_cascade = _fake_call_with_cascade

        plan, step = _plan_and_step()
        events = [e async for e in executor.execute_step(plan, step)]

        assert "messages" in captured, "cascade was never called"
        assert captured["messages"][-1] == {"role": "user", "content": block}

    async def test_no_block_when_unset(self, monkeypatch):
        executor = _make_executor(session_constraints=None)

        captured: dict = {}

        async def _fake_call_with_cascade(messages, description):
            captured["messages"] = messages
            return _FakeCascadeResponse()

        executor._cascade.call_with_cascade = _fake_call_with_cascade

        plan, step = _plan_and_step()
        [e async for e in executor.execute_step(plan, step)]

        assert captured["messages"][-1]["content"] is not None
        # Last message is the normal context/buffer content, not a constraint block.
        assert "SESSION CONSTRAINTS" not in captured["messages"][-1]["content"]

    async def test_block_survives_multiple_iterations_not_buffer(self, monkeypatch):
        """The block must be re-appended fresh each loop iteration (never
        pushed into _conversation_buffer, which is evictable/compactable)."""
        block = "## SESSION CONSTRAINTS\n  - never delete files"
        executor = _make_executor(session_constraints=block)

        call_count = 0
        captured_per_call: list = []

        async def _fake_call_with_cascade(messages, description):
            nonlocal call_count
            call_count += 1
            captured_per_call.append(list(messages))
            if call_count == 1:
                # First turn: emit a tool call so the loop iterates again.
                return _FakeCascadeResponse(content="calling a tool", tool_calls=[])
            return _FakeCascadeResponse(content="done", tool_calls=[])

        executor._cascade.call_with_cascade = _fake_call_with_cascade

        plan, step = _plan_and_step()
        [e async for e in executor.execute_step(plan, step)]

        # Regardless of iteration count, every wire call ends with the block.
        for messages in captured_per_call:
            assert messages[-1] == {"role": "user", "content": block}
