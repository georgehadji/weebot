"""A tripwire on a known defect, not a specification.

D20. `PlanActFlow.run()` resets `prompt_consumed` when
`type(self._state) != self._last_state_type`, so that "each FlowState gets one
chance at the prompt". That condition never becomes true: `set_state` is the
only live writer of `self._state` and it assigns `_last_state_type` in the same
call, so the two are always equal when the loop next looks.

Measured on a real flow driven through `run()`: `PlanningState` received
'THE ORIGINAL TASK' and `ExecutingState`, one transition later and a different
state type, received ''. `PlanningState` already carries a local workaround for
this, with a comment naming the flag.

The recorded claim — "terminate-with-next-step returns without `set_state`" —
had the mechanism backwards. It is not a missing `set_state`; it is `set_state`
defeating the check.

These tests PIN THE CURRENT, DEFECTIVE BEHAVIOUR. Repairing the reset changes
what every state is handed, `ExecutingState`'s `user_input` included, which is a
change to the product's model inputs and not something to slip in. When someone
makes that change deliberately, these tests fail and this docstring is the note
explaining what they just turned on.
"""

from __future__ import annotations

import types

import pytest

from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig
from weebot.application.flows.states import completed as completed_mod
from weebot.application.flows.states import executing as executing_mod
from weebot.application.flows.states import planning as planning_mod
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.event import DoneEvent, MessageEvent
from weebot.domain.models.session import Session


class _DummyLLM:
    async def chat(self, **_):
        return types.SimpleNamespace(content="{}", model="x", usage=None)


def test_set_state_leaves_the_reset_condition_unsatisfiable():
    """The mechanism, isolated: the comparison's two sides are written together."""
    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_DummyLLM(),
            tools=ToolCollection(),
            session=Session(id="s1", task="t"),
            max_iterations=1,
        )
    )
    flow.set_state(planning_mod.PlanningState())
    assert type(flow._state) is flow._last_state_type

    flow.set_state(executing_mod.ExecutingState())
    assert type(flow._state) is flow._last_state_type, (
        "if these ever differ after set_state, the run loop's prompt_consumed "
        "reset can fire and this file's premise no longer holds"
    )


@pytest.mark.asyncio
async def test_a_later_state_receives_no_prompt(monkeypatch):
    """The consequence, through the real run loop."""
    seen: list[tuple[str, str]] = []

    def _recorder(name: str, next_state):
        async def execute(self, context, prompt):
            seen.append((name, prompt))
            yield MessageEvent(role="assistant", message=f"{name} ran")
            context.set_state(next_state())

        return execute

    monkeypatch.setattr(
        planning_mod.PlanningState,
        "execute",
        _recorder("PlanningState", executing_mod.ExecutingState),
    )
    monkeypatch.setattr(
        executing_mod.ExecutingState,
        "execute",
        _recorder("ExecutingState", completed_mod.CompletedState),
    )
    monkeypatch.setattr(
        completed_mod.CompletedState,
        "execute",
        _recorder("CompletedState", completed_mod.CompletedState),
    )

    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_DummyLLM(),
            tools=ToolCollection(),
            session=Session(id="s1", task="t"),
            max_iterations=4,
        )
    )
    async for event in flow.run("THE ORIGINAL TASK"):
        if isinstance(event, DoneEvent):
            break

    by_state = dict(seen)
    assert by_state.get("PlanningState") == "THE ORIGINAL TASK"
    assert "ExecutingState" in by_state, "the flow never reached a second state type"
    assert by_state["ExecutingState"] == "", (
        "ExecutingState received the prompt — the reset now fires. That is the "
        "documented INTENT, so this is good news, but it changes what the "
        "executor is handed as user_input across the product. Read this file's "
        "docstring, then delete these two assertions deliberately."
    )


def test_the_one_writer_that_would_trip_it_has_no_callers():
    """`AgentSessionManager.set_state` does `flow._state = state` and never
    touches `_last_state_type` — a second, near-duplicate transition
    implementation that omits the field the run loop depends on. It has no
    callers, which is the only reason it is not a live inconsistency.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[4]
    importers = []
    for path in list((root / "weebot").rglob("*.py")) + list((root / "cli").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if "agent_session_manager" in rel or "__pycache__" in rel:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.rsplit(".", 1)[-1] == "agent_session_manager":
                    importers.append(rel)

    assert not importers, (
        f"AgentSessionManager is now imported by {importers}; its set_state omits "
        "_last_state_type, so the two transition implementations disagree in a way "
        "that is now reachable"
    )
