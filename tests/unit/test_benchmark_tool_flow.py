"""`benchmark run` and `batch` must drive the flow `flow run` builds: real tools, AUTO mode,
and a usage tally on the event bus. The target flow factory they used before passed
``tools=None``, so no tool-using task could run. No LLM, no network."""

from __future__ import annotations

import types

import pytest

from cli.commands import harness
from weebot.application.cqrs.mediator import Mediator
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.scoring_port import ScoringPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.execution_mode import ExecutionMode
from weebot.domain.models.session import Session


class _Bus:
    def __init__(self):
        self.handlers = []

    def subscribe_domain(self, handler):
        self.handlers.append(handler)


class _Repo:
    def __init__(self):
        self.saved = []

    async def save_session(self, session):
        self.saved.append(session.id)


class _Container:
    def __init__(self):
        self.bus = _Bus()
        self.repo = _Repo()
        self.llm = object()
        self.asked_model = None
        self._by_port = {
            EventBusPort: self.bus,
            LLMPort: self.llm,
            Mediator: object(),
            StateRepositoryPort: self.repo,
            ScoringPort: object(),
        }

    def get(self, port):
        return self._by_port[port]

    def create_llm_for_model(self, model):
        self.asked_model = model
        return ("llm-for", model)


class _Tools:
    torn_down = False

    async def teardown(self):
        self.torn_down = True


@pytest.fixture
def wired(monkeypatch):
    container, tools, created = _Container(), _Tools(), []

    async def build_tools(role="admin", llm_port=None, **_):
        created.append(("tools", role, llm_port))
        return tools

    def create_flow(**kwargs):
        created.append(("flow", kwargs))
        return types.SimpleNamespace()

    import weebot.interfaces.factories as factories

    monkeypatch.setattr(factories, "shared_container", lambda: container)
    monkeypatch.setattr(factories, "build_tools", build_tools)
    monkeypatch.setattr(factories, "create_flow", create_flow)
    monkeypatch.setattr("weebot.config.feature_flags.SCORING_MODE", "plan_outcome")
    return container, tools, created


async def test_the_flow_gets_real_tools_and_runs_unattended(wired):
    container, tools, created = wired

    runner, got_tools = await harness._tool_runner(None, "general")
    runner._flow_factory(Session(id="s1", user_id="b", agent_id="b"))

    assert got_tools is tools
    assert created[0] == ("tools", "admin", container.llm)
    flow_kwargs = created[1][1]
    assert flow_kwargs["tools"] is tools
    assert flow_kwargs["flow_type"] == "plan_act"
    assert flow_kwargs["execution_mode"] == ExecutionMode.AUTO
    assert flow_kwargs["event_bus"] is container.bus


async def test_usage_is_counted_from_the_same_bus_the_flow_publishes_on(wired):
    container, _, _ = wired

    runner, _ = await harness._tool_runner(None, "general")

    assert container.bus.handlers == [runner._usage.on_domain_event]


async def test_a_model_override_goes_to_the_container(wired):
    container, _, created = wired

    await harness._tool_runner("some/model", "general")

    assert container.asked_model == "some/model"
    assert created[0][2] == ("llm-for", "some/model")


async def test_the_session_is_saved_before_the_flow_looks_it_up(wired):
    container, _, _ = wired
    runner, _ = await harness._tool_runner(None, "general")

    await runner._prepare(Session(id="s9", user_id="b", agent_id="b"))

    assert container.repo.saved == ["s9"]


async def test_a_flow_error_event_becomes_the_result_error():
    from weebot.application.harness.runner import BenchmarkRunner
    from weebot.domain.models.benchmark_task import SamplePair, WeebotTask

    class _Flow:
        async def run(self, prompt):
            yield types.SimpleNamespace(type="error", error="Plan creation rejected: nope")

    prepared = []

    async def prepare(session):
        prepared.append(session.id)

    runner = BenchmarkRunner(flow_factory=lambda s: _Flow(), prepare=prepare)
    task = WeebotTask(task_id="t", description="", samples=(SamplePair("p", "1"),))

    result = await runner.run_task(task, 0)

    assert result.error == "Plan creation rejected: nope" and not result.passed
    assert len(prepared) == 1


async def test_a_short_answer_the_executor_replaced_with_filler_is_scored():
    from weebot.application.harness.runner import _FILLER_REPLY, BenchmarkRunner
    from weebot.domain.models.benchmark_task import SamplePair, WeebotTask
    from weebot.domain.models.event import MessageEvent, ThoughtEvent

    class _Flow:
        def __init__(self, session):
            self._session = session

        async def run(self, prompt):
            yield ThoughtEvent(step_id="s", thought="42", iteration=1)
            self._session = self._session.model_copy(
                update={"events": [MessageEvent(role="assistant", message=_FILLER_REPLY)]}
            )
            yield MessageEvent(role="assistant", message=_FILLER_REPLY)

    runner = BenchmarkRunner(flow_factory=_Flow)
    task = WeebotTask(task_id="t", description="", samples=(SamplePair("p", "42"),))

    result = await runner.run_task(task, 0)

    assert result.answer == "42" and result.passed
