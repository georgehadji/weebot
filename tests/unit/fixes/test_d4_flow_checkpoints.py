"""D4: flows checkpoint after each step, and an interrupted session can be recovered.

The checkpoint store and scheduler were half wired: `flow._checkpoint_port` was set
and never read, nothing built a CheckpointScheduler, nothing read a checkpoint
back, and the store needed a table only alembic creates (the CLI never runs it).
Now (WEEBOT_FLOW_CHECKPOINTS):
- the store keeps its own file and creates its table on first save;
- PlanActFlow saves a checkpoint after every step event, naming the state by id;
- `restore_from_checkpoint` puts the checkpointed plan back into a session whose
  own copy fell behind, and `TaskRunner.resume_from_checkpoint` re-runs it;
- the delete cascade purges checkpoints, whether or not the flag is on.
"""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from weebot.application.flows._checkpoint_scheduler import (
    CheckpointScheduler,
    restore_from_checkpoint,
)
from weebot.domain.models.checkpoint import FlowCheckpoint
from weebot.domain.models.event import PlanEvent, StepEvent
from weebot.domain.models.plan import Plan, Step, StepStatus
from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.checkpoint_store import SQLiteCheckpointStore


def _plan(done: int, total: int = 3) -> Plan:
    return Plan(
        title="p",
        steps=[
            Step(
                id=f"s{i}",
                description=f"step {i}",
                status=StepStatus.COMPLETED if i < done else StepStatus.PENDING,
                result=f"result {i}" if i < done else None,
            )
            for i in range(total)
        ],
    )


async def test_the_store_creates_its_own_table_and_round_trips(tmp_path):
    store = SQLiteCheckpointStore(db_path=str(tmp_path / "cp.db"))
    checkpoint = FlowCheckpoint(
        session_id="s1", flow_type="PlanActFlow", current_state="executing", plan_snapshot=_plan(1)
    )
    await store.save(checkpoint)
    loaded = await store.load("s1")
    assert loaded is not None and loaded.current_state == "executing"
    assert await store.delete("s1") is True


async def test_deleting_from_an_unused_store_creates_no_file(tmp_path):
    store = SQLiteCheckpointStore(db_path=str(tmp_path / "cp.db"))
    assert await store.delete("nobody") is False
    assert await store.load("nobody") is None
    assert not (tmp_path / "cp.db").exists()


async def test_the_scheduler_names_the_state_and_summarises_the_work():
    port = SimpleNamespace(save=AsyncMock())
    from weebot.application.flows.states.executing import ExecutingState

    session = Session(id="s1", user_id="u", agent_id="a")
    await CheckpointScheduler(port).maybe_save(session, _plan(2), ExecutingState())
    saved = port.save.await_args.args[0]
    assert saved.current_state == "executing"
    assert "result 1" in saved.conversation_summary
    assert [c.step_id for c in saved.completed_steps] == ["s0", "s1"]


def _checkpoint(done: int) -> FlowCheckpoint:
    return FlowCheckpoint(
        session_id="s1",
        flow_type="PlanActFlow",
        current_state="executing",
        plan_snapshot=_plan(done),
    )


def test_a_session_behind_its_checkpoint_gets_the_checkpointed_plan():
    session = Session(id="s1", user_id="u", agent_id="a").add_event(
        PlanEvent(plan=_plan(0).model_dump())
    )
    restored = restore_from_checkpoint(session, _checkpoint(2))
    plan = restored.get_last_plan()
    assert [s.status for s in plan.steps][:2] == [StepStatus.COMPLETED, StepStatus.COMPLETED]
    assert restored.status == SessionStatus.WAITING


def test_a_session_ahead_of_its_checkpoint_keeps_its_own_plan():
    session = Session(id="s1", user_id="u", agent_id="a").add_event(
        PlanEvent(plan=_plan(3).model_dump())
    )
    restored = restore_from_checkpoint(session, _checkpoint(1))
    assert all(s.status == StepStatus.COMPLETED for s in restored.get_last_plan().steps)


def _flow(resolve):
    from weebot.application.flows.flow_builder import build_flow
    from weebot.application.models.tool_collection import ToolCollection

    return build_flow(
        resolve=resolve,
        flow_type="plan_act",
        session=Session(id="s-flow", user_id="u", agent_id="a"),
        llm=MagicMock(),
        tools=ToolCollection(),
        mediator=MagicMock(),
    )


async def test_the_flow_saves_a_checkpoint_after_a_step_only_while_the_flag_is_on(monkeypatch):
    import weebot.config.feature_flags as flags
    from weebot.application.ports.checkpoint_port import CheckpointPort

    port = SimpleNamespace(save=AsyncMock())

    def resolve(key):
        return port if key is CheckpointPort else None

    monkeypatch.delenv("WEEBOT_FLOW_CHECKPOINTS", raising=False)
    importlib.reload(flags)
    assert _flow(resolve)._checkpoints is None

    monkeypatch.setenv("WEEBOT_FLOW_CHECKPOINTS", "1")
    importlib.reload(flags)
    try:
        flow = _flow(resolve)
        flow._plan = _plan(1)
        await flow._emit(StepEvent(step_id="s0", status=StepStatus.COMPLETED))
        port.save.assert_awaited_once()
    finally:
        monkeypatch.delenv("WEEBOT_FLOW_CHECKPOINTS")
        importlib.reload(flags)


async def test_the_task_runner_resumes_from_a_checkpoint(monkeypatch):
    from weebot.application.services.task_runner import TaskRunner

    session = Session(id="s1", user_id="u", agent_id="a").set_status(SessionStatus.FAILED)
    repo = SimpleNamespace(load_session=AsyncMock(return_value=session), save_session=AsyncMock())
    runner = TaskRunner(state_repo=repo)
    started = []

    async def start(s, factory, prompt=None):
        started.append((s, prompt))
        return s

    monkeypatch.setattr(runner, "_start_direct", start)
    store = SimpleNamespace(load=AsyncMock(return_value=_checkpoint(2)))
    await runner.resume_from_checkpoint("s1", flow_factory=object(), checkpoints=store)
    resumed, prompt = started[0]
    assert resumed.get_last_plan().steps[1].status == StepStatus.COMPLETED
    assert prompt == ""


def test_the_delete_cascade_purges_checkpoints():
    from weebot.application.ports.checkpoint_port import CheckpointPort
    from weebot.interfaces.web.dependencies import _session_stores

    assert ("flow_checkpoints", CheckpointPort, "delete") in _session_stores()
