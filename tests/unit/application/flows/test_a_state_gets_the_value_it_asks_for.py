"""`prompt` means two different things, and each state now gets the one it wants.

D74. `PlanActFlow.run()` hands the turn's user input to one state and `""` to
every state after it. A reset was written to re-arm that on each state-type
change — "each FlowState gets one chance at the prompt" — and it never fired,
because `set_state` wrote `_last_state_type` in the same call that wrote
`_state`, so the comparison's two sides were always equal by the time the loop
looked.

Making it fire would have been the wrong repair. Measured against the code that
reads the value, `prompt` carries two incompatible meanings:

  turn input   ExecutorAgent appends it as a user turn "so the LLM sees the
               answer instead of calling ask_human again"; BehavioralLearner
               passes it to `learn_from_correction`. Both want *what the user
               said on this turn* — and `""` after the first state is the
               correct answer for both.

  the task     CritiquingState, ReviewingState, UpdatingState, PremortmState,
               MetaAnalysisState and CompletedState read it as the task. A plan
               critic scoring a plan against `""` is not scoring it against
               anything, and CompletedState keyed every plan template it wrote
               on `compute_task_hash("")`.

So the reset was deleted and the six task-wanting sites were pointed at
`task_text`, which is the fallback `PlanningState` had already written inline
with a comment naming the flag.

These tests pin BOTH halves: the task sites get the task, and the turn-input
sites still get "".
"""

from __future__ import annotations

import ast
import pathlib
import types

import pytest

from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig
from weebot.application.flows.states import completed as completed_mod
from weebot.application.flows.states import executing as executing_mod
from weebot.application.flows.states import planning as planning_mod
from weebot.application.flows.states.base import task_text
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.event import DoneEvent, MessageEvent
from weebot.domain.models.session import Session, SessionContext

_ROOT = pathlib.Path(__file__).resolve().parents[4]
_STATES = _ROOT / "weebot" / "application" / "flows" / "states"


class _DummyLLM:
    async def chat(self, **_):
        return types.SimpleNamespace(content="{}", model="x", usage=None)


def _flow(session: Session | None = None, max_iterations: int = 1) -> PlanActFlow:
    return PlanActFlow(
        PlanActFlowConfig(
            llm=_DummyLLM(),
            tools=ToolCollection(),
            session=session or Session(id="s1", task="t"),
            max_iterations=max_iterations,
        )
    )


# ── the task half ────────────────────────────────────────────────────────


def test_task_text_falls_back_to_the_original_task():
    flow = _flow(
        Session(id="s1", task="t", context=SessionContext(original_task="THE ORIGINAL TASK"))
    )
    assert task_text(flow, "") == "THE ORIGINAL TASK"
    assert task_text(flow, "   ") == "THE ORIGINAL TASK"


def test_task_text_prefers_the_turn_input_when_there_is_one():
    """A resume turn's text is the more specific answer; it wins."""
    flow = _flow(
        Session(id="s1", task="t", context=SessionContext(original_task="THE ORIGINAL TASK"))
    )
    assert task_text(flow, "use Postgres instead") == "use Postgres instead"


def test_task_text_returns_empty_rather_than_inventing_a_task():
    flow = _flow(Session(id="s1", task="t", context=SessionContext()))
    assert task_text(flow, "") == ""


def _calls_named(tree: ast.AST, name: str) -> list[ast.Call]:
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and (
            (isinstance(n.func, ast.Name) and n.func.id == name)
            or (isinstance(n.func, ast.Attribute) and n.func.attr == name)
        )
    ]


def _is_task_text_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "task_text"
    )


@pytest.mark.parametrize(
    "module",
    [
        "critiquing.py",
        "reviewing.py",
        "updating.py",
        "premortem.py",
        "meta_analysis.py",
        "completed.py",
        "executing.py",
        "planning.py",
    ],
)
def test_every_task_wanting_state_asks_for_the_task(module: str):
    """Each of these read a bare `prompt` as if it were the task."""
    tree = ast.parse((_STATES / module).read_text(encoding="utf-8"))
    assert _calls_named(tree, "task_text"), (
        f"{module} no longer calls task_text; if a site was removed on purpose, "
        "drop it from this list, but a bare `prompt` read as the task is the "
        "defect D74 closed"
    )


@pytest.mark.parametrize("module", ["critiquing.py", "reviewing.py", "updating.py"])
def test_the_critique_task_key_is_not_a_bare_prompt(module: str):
    """These three build `{"task": ...}` for a plan critic. Measured before the
    fix: the value was `prompt`, which is `""` in every state but the first."""
    tree = ast.parse((_STATES / module).read_text(encoding="utf-8"))
    values = [
        value
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values)
        if isinstance(key, ast.Constant) and key.value == "task"
    ]
    assert values, f'{module} no longer builds a "task" key'
    for value in values:
        assert _is_task_text_call(value), (
            f'{module} passes {ast.dump(value)} as "task"; a critic scoring a '
            'plan against the turn input scores it against "" after the '
            "first state"
        )


# ── the turn-input half ──────────────────────────────────────────────────


def test_the_executor_and_the_learner_still_read_the_turn_input():
    """The two sites that must NOT be handed the task.

    If these ever route through `task_text`, the original task is replayed to
    the model as a fresh user turn on every re-entry to ExecutingState, and
    mined for behavioural rules as though the user had corrected the agent.
    """
    tree = ast.parse((_STATES / "executing.py").read_text(encoding="utf-8"))

    learn = _calls_named(tree, "learn_from_correction")
    assert len(learn) == 1, "expected exactly one learn_from_correction call"
    first_arg = learn[0].args[0]
    assert isinstance(first_arg, ast.Name) and first_arg.id == "prompt", (
        f"learn_from_correction is now passed {ast.dump(first_arg)}. It mines its "
        "argument for behavioural rules as though the user had corrected the "
        "agent; the original task is not a correction"
    )

    commands = _calls_named(tree, "ExecuteStepCommand")
    assert len(commands) == 1, "expected exactly one ExecuteStepCommand construction"
    user_input = [kw.value for kw in commands[0].keywords if kw.arg == "user_input"]
    assert len(user_input) == 1, "ExecuteStepCommand no longer takes user_input"
    assert isinstance(user_input[0], ast.Name) and user_input[0].id == "effective_prompt", (
        f"user_input is now {ast.dump(user_input[0])}. The executor appends it as "
        "a user turn; handing it the original task replays the task to the model "
        "on every re-entry to ExecutingState"
    )


@pytest.mark.asyncio
async def test_a_later_state_receives_no_turn_input(monkeypatch):
    """The run loop's contract, through the real loop: one state, one prompt."""
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

    flow = _flow(max_iterations=4)
    async for event in flow.run("THE ORIGINAL TASK"):
        if isinstance(event, DoneEvent):
            break

    by_state = dict(seen)
    assert by_state.get("PlanningState") == "THE ORIGINAL TASK"
    assert "ExecutingState" in by_state, "the flow never reached a second state type"
    assert by_state["ExecutingState"] == "", (
        "ExecutingState was handed the turn input again. It forwards this to the "
        "executor as `user_input` and to `learn_from_correction`; replaying the "
        "original task there is the repair D74 deliberately did not make. Read "
        "this file's docstring before changing it."
    )


# ── the machinery that is gone ───────────────────────────────────────────


def test_the_dead_reset_and_the_field_it_read_are_gone():
    """`_last_state_type` existed only to serve a condition that never fired.

    Left in place it is an invitation: the obvious "fix" is to make the reset
    work, which is the change this file's docstring explains is wrong.
    """
    src = (_ROOT / "weebot" / "application" / "flows" / "plan_act_flow.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    live = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "_last_state_type"
    ]
    assert not live, "_last_state_type is referenced in code again"


def test_the_duplicate_transition_implementation_still_has_no_callers():
    """`AgentSessionManager.set_state` does `flow._state = state` and never sets
    `flow.status`, which is how the rest of the product reads the flow's
    position. It is a second transition implementation that disagrees with the
    first; it has no callers, which is the only reason that is not live.
    """
    importers = []
    for path in list((_ROOT / "weebot").rglob("*.py")) + list((_ROOT / "cli").rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
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
        "flow.status, so the two transition implementations disagree in a way "
        "that is now reachable"
    )
