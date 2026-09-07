"""The plan-template cache is off unless someone turns it on.

Both sides of this feature raised TypeError on every call for its entire
existence (D75/D76), each swallowed by an `except Exception: logger.debug(...)`,
so `plan_templates` had never held a row and the planner had never been seeded.
Repairing the calls therefore did not restore a behaviour — it started one, on
every task, in the planner's inputs.

`PLAN_TEMPLATE_CACHE_ENABLED` makes that a decision. One flag covers both the
write and the read: gating only the read would leave the table growing for a
feature that is off, and nothing prunes it.

These tests pin the default, and pin that the flag actually reaches both call
sites — a flag that is defined and not consulted is worse than no flag, because
it reads as protection that is not there.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import json
import pathlib
import types
import uuid
from unittest.mock import patch

import pytest

import weebot.config.feature_flags as flags
from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig
from weebot.application.flows.states.completed import CompletedState
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.plan import Plan, Step, StepStatus
from weebot.domain.models.session import Session, SessionContext
from weebot.domain.services.plan_template_cache import compute_task_hash
from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository

_ROOT = pathlib.Path(__file__).resolve().parents[2]

TASK = "build a responsive marketing website"


class _DummyLLM:
    async def chat(self, **_):
        return types.SimpleNamespace(content="{}", model="x", usage=None)


@pytest.fixture
async def repo(tmp_path):
    r = SQLiteStateRepository(db_path=str(tmp_path / "t.db"))
    await r._init_helpers()
    yield r
    await r.close()


@pytest.fixture
def no_background_work(monkeypatch):
    """Stub the post-completion background work these tests do not exercise.

    `CompletedState` ends by spawning a retention review, skill-gap processing
    and a dream scan (P3-4). Each builds a `Container()` and live LLM adapters,
    so driving the real state in a unit test otherwise reaches the network and
    then outlives the test — the tasks run on into fixture teardown and raise
    "Event loop is closed". The subject here is the template save, not that
    tail, so it is replaced rather than waited on.
    """
    from weebot.application.flows.states import completed as mod

    spawned: list[str] = []

    class _Recorder:
        def spawn(self, coro, *, name: str):
            spawned.append(name)
            coro.close()  # never awaited; close it so Python does not warn

            async def _noop() -> None:
                return None

            return asyncio.get_running_loop().create_task(_noop())

    monkeypatch.setattr(mod, "_background", lambda: _Recorder())
    return spawned


def _flow(repo) -> PlanActFlow:
    session = Session(id="s1", task=TASK, context=SessionContext(original_task=TASK))
    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_DummyLLM(), tools=ToolCollection(), session=session, max_iterations=1
        )
    )
    flow._state_repo = repo
    flow._plan = Plan(
        id="p1",
        title=TASK,
        steps=[
            Step(id="1", description="scaffold", status=StepStatus.COMPLETED),
            Step(id="2", description="style", status=StepStatus.COMPLETED),
            Step(id="3", description="deploy", status=StepStatus.FAILED),
        ],
    )
    return flow


# ── the default ──────────────────────────────────────────────────────────


def test_the_flag_is_off_by_default():
    assert flags.PLAN_TEMPLATE_CACHE_ENABLED is False


def test_the_environment_variable_turns_it_on():
    with patch.dict("os.environ", {"WEEBOT_PLAN_TEMPLATE_CACHE": "true"}):
        reloaded = importlib.reload(flags)
        try:
            assert reloaded.PLAN_TEMPLATE_CACHE_ENABLED is True
        finally:
            importlib.reload(flags)


# ── the write side ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_template_is_written_while_the_flag_is_off(repo, monkeypatch, no_background_work):
    monkeypatch.setattr(flags, "PLAN_TEMPLATE_CACHE_ENABLED", False)

    async for _ in CompletedState().execute(_flow(repo), ""):
        pass

    assert await repo.list_all_plan_templates() == []


@pytest.mark.asyncio
async def test_a_template_is_written_once_the_flag_is_on(repo, monkeypatch, no_background_work):
    monkeypatch.setattr(flags, "PLAN_TEMPLATE_CACHE_ENABLED", True)

    async for _ in CompletedState().execute(_flow(repo), ""):
        pass

    rows = await repo.list_all_plan_templates()
    assert len(rows) == 1
    # D74: keyed on the task, not on the "" the run loop hands this state.
    assert rows[0]["task_hash"] == compute_task_hash(TASK)
    assert rows[0]["task_description"] == TASK
    # D77: the computed score, not the column default of 1.0.
    assert rows[0]["success_score"] == 0.67


# ── the read side ────────────────────────────────────────────────────────


async def _seed(repo) -> None:
    await repo.save_plan_template(
        str(uuid.uuid4()),
        compute_task_hash(TASK),
        TASK,
        json.dumps({"title": TASK, "steps": []}),
        1.0,
    )


async def _meta_notes_the_planner_receives(repo, monkeypatch) -> list[str] | None:
    """Drive the real CreatePlanHandler and capture what it hands the planner."""
    from weebot.application.agents import planner as planner_mod
    from weebot.application.cqrs.commands import CreatePlanCommand
    from weebot.application.cqrs.handlers.create_plan_handler import CreatePlanHandler

    seen: dict[str, list[str] | None] = {}

    class _StubPlanner:
        def __init__(self, **_):
            pass

        async def create_plan(self, prompt, meta_notes=None):
            seen["meta_notes"] = meta_notes
            return
            yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(planner_mod, "PlannerAgent", _StubPlanner)

    await repo.save_session(Session(id="s-plan", task=TASK))
    result = await CreatePlanHandler(state_repo=repo, llm=_DummyLLM()).handle(
        CreatePlanCommand(session_id="s-plan", prompt=TASK)
    )
    assert result.success, result.error
    return seen["meta_notes"]


@pytest.mark.asyncio
async def test_the_planner_is_not_seeded_while_the_flag_is_off(repo, monkeypatch):
    """The half that changes the planner's inputs, with a template available."""
    await _seed(repo)
    monkeypatch.setattr(flags, "PLAN_TEMPLATE_CACHE_ENABLED", False)

    assert await _meta_notes_the_planner_receives(repo, monkeypatch) is None


@pytest.mark.asyncio
async def test_the_planner_is_seeded_once_the_flag_is_on(repo, monkeypatch):
    await _seed(repo)
    monkeypatch.setattr(flags, "PLAN_TEMPLATE_CACHE_ENABLED", True)

    notes = await _meta_notes_the_planner_receives(repo, monkeypatch)

    assert notes, "the flag is on and a template matches, but the planner got nothing"
    assert TASK in "\n".join(notes)


# ── the flag actually reaches both call sites ────────────────────────────


@pytest.mark.parametrize(
    "relpath",
    [
        "weebot/application/flows/states/completed.py",
        "weebot/application/cqrs/handlers/create_plan_handler.py",
    ],
)
def test_both_call_sites_consult_the_flag(relpath: str):
    tree = ast.parse((_ROOT / relpath).read_text(encoding="utf-8"))
    names = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == "PLAN_TEMPLATE_CACHE_ENABLED"
    ]
    assert names, (
        f"{relpath} no longer consults PLAN_TEMPLATE_CACHE_ENABLED — the flag "
        "would read as protection that is not there"
    )
