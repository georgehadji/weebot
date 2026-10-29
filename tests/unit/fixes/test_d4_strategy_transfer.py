"""D4: approaches that worked in one kind of task are offered when planning another.

StrategyTransferService and its store had no producer, no consumer and no
registration, and the store wrote to a file in the working directory. Now
(WEEBOT_STRATEGY_TRANSFER):
- CompletedState records a fully successful plan's approach, once per task,
  under the task's category (coding, research, ...);
- PlanningState adds up to two approaches from OTHER categories as notes.
"""

import importlib
from unittest.mock import MagicMock

import pytest

from weebot.application.services.strategy_transfer import StrategyTransferService
from weebot.domain.models.plan import Plan, Step, StepStatus
from weebot.infrastructure.persistence.strategy_store import StrategyStore


def _plan(status=StepStatus.COMPLETED):
    return Plan(
        title="t",
        steps=[
            Step(id="1", description="outline the sources", status=StepStatus.COMPLETED),
            Step(id="2", description="draft and cite", status=status),
        ],
    )


@pytest.fixture
def service(tmp_path):
    return StrategyTransferService(StrategyStore(db_path=tmp_path / "s.db"), min_score=0.7)


async def test_a_success_is_recorded_once_per_task_and_offered_to_other_domains(service):
    await service.record_success("research the history of the printing press", _plan())
    await service.record_success("research the history of the printing press", _plan())
    failed = _plan(StepStatus.FAILED)
    await service.record_success("write a python script to parse csv files", failed)

    coding_notes = await service.notes_for("write a python function to sort lists")
    assert len(coding_notes) == 1 and "outline the sources" in coding_notes[0]
    # Same domain: transfer is across domains, and plan templates cover same-task reuse.
    assert await service.notes_for("research the history of the steam engine") == []


def test_the_store_needs_an_explicit_path():
    with pytest.raises(TypeError):
        StrategyStore()


def _flow(resolve):
    from weebot.application.flows.flow_builder import build_flow
    from weebot.application.models.tool_collection import ToolCollection
    from weebot.domain.models.session import Session

    return build_flow(
        resolve=resolve,
        flow_type="plan_act",
        session=Session(id="s-flow", user_id="u", agent_id="a"),
        llm=MagicMock(),
        tools=ToolCollection(),
        mediator=MagicMock(),
    )


def test_the_flow_gets_the_service_only_while_the_flag_is_on(monkeypatch):
    import weebot.config.feature_flags as flags
    from weebot.application.di.keys import STRATEGY_TRANSFER

    svc = object()

    def resolve(key):
        return svc if key == STRATEGY_TRANSFER else None

    monkeypatch.delenv("WEEBOT_STRATEGY_TRANSFER", raising=False)
    importlib.reload(flags)
    assert _flow(resolve)._strategy_transfer is None
    monkeypatch.setenv("WEEBOT_STRATEGY_TRANSFER", "1")
    importlib.reload(flags)
    try:
        assert _flow(resolve)._strategy_transfer is svc
    finally:
        monkeypatch.delenv("WEEBOT_STRATEGY_TRANSFER")
        importlib.reload(flags)


def test_completed_and_planning_states_use_it():
    from pathlib import Path

    states = Path("weebot/application/flows/states")
    assert ".record_success(" in (states / "completed.py").read_text(encoding="utf-8")
    assert ".notes_for(" in (states / "planning.py").read_text(encoding="utf-8")


def test_the_knowledge_graph_service_is_still_bound():
    from weebot.application.di import Container

    container = Container()
    container.configure_knowledge_graph(db_path="unused.db")
    assert "knowledge_graph" in container._bindings
