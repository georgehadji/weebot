"""D4: the harness gate judges a task by how its flow ended, and sees its answer.

Before:
- `HarnessOptFlow`'s task runner counted a task as passed whenever `flow.run()`
  did not raise. PlanActFlow reports failure through the session status, not an
  exception, so the regression gate saw almost no failures.
- It scored the Session it created, but the flow replaces its session as the run
  goes, so the metrics came from an empty one.
- It built a PlanActFlow with no mediator, which planning refuses to run.
- The gate's CodeQualitySignal read a `trace` the runner never wrote, so it scored
  the task id; and `harness evolve` never passed a signal at all.
- `harness baseline`, `harness run` and `harness compare` called
  `_create_target_flow_factory()` without the `db_path` it required.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from weebot.application.flows.harness_opt_flow import HarnessOptFlow
from weebot.config.harness.schema import HarnessConfig
from weebot.domain.models.event import MessageEvent
from weebot.domain.models.session import SessionStatus


def _factory(status: SessionStatus, answer: str = "the answer"):
    seen = {}

    def factory(session, harness_config=None):
        seen["config"] = harness_config

        class _Flow:
            _session = session

            async def run(self, _prompt):
                done = self._session.add_event(MessageEvent(role="assistant", message=answer))
                self._session = done.set_status(status)
                if False:
                    yield None

        return _Flow()

    return factory, seen


def _runner(factory):
    flow = HarnessOptFlow(
        llm=MagicMock(), target=MagicMock(), trajectory_repo=MagicMock(), flow_factory=factory
    )
    return flow._make_task_runner()


async def test_a_flow_that_ends_failed_is_a_failed_task():
    factory, _ = _factory(SessionStatus.FAILED)
    [result] = await _runner(factory)(["do x"], HarnessConfig.default())
    assert result["passed"] is False


async def test_a_completed_flow_passes_and_its_answer_is_the_trace():
    factory, seen = _factory(SessionStatus.COMPLETED)
    config = HarnessConfig.default()
    [result] = await _runner(factory)(["do x"], config)
    assert result["passed"] is True
    assert result["trace"] == "the answer"
    assert seen["config"] is config


def test_the_target_flow_factory_needs_no_db_path():
    from weebot.application.di import Container

    factory = Container()._create_target_flow_factory()
    assert callable(factory)


def test_harness_evolve_passes_the_quality_signal_and_the_flow_factory():
    from pathlib import Path

    src = Path("cli/commands/harness.py").read_text(encoding="utf-8")
    assert "code_quality_signal=" in src and "--quality-signal" in src
    evolve = src.split("def harness_evolve")[1]
    assert "flow_factory=container._create_target_flow_factory()" in evolve


async def test_the_gate_scores_the_trace_not_the_task_id():
    from weebot.application.services.regression_gate import RegressionGate

    calls = []

    async def fast_reject(task_prompt, agent_output):
        calls.append(agent_output)
        return False

    async def runner(task_ids, config):
        return [{"passed": False, "task_id": t, "trace": "wrong output"} for t in task_ids]

    signal = SimpleNamespace(fast_reject=fast_reject)
    gate = RegressionGate(task_runner=runner, code_quality_signal=signal)
    await gate._run_split(["t1"], HarnessConfig.default(), HarnessConfig.default(), repeats=1)
    assert calls and set(calls) == {"wrong output"}


def _signal(content: str):
    from unittest.mock import AsyncMock

    from weebot.application.services.code_quality_signal import CodeQualitySignal

    llm = SimpleNamespace(chat=AsyncMock(return_value=SimpleNamespace(content=content)))
    return CodeQualitySignal(llm=llm)


async def test_the_signal_rejects_poor_output_even_when_fenced():
    scores = '{"artifact_presence": 0, "verification_evidence": 0, "structure_quality": 0.1}'
    poor = f"```json\n{scores}\n```"
    assert await _signal(poor).fast_reject("t", "out") is True


async def test_the_signal_keeps_good_output():
    good = '{"artifact_presence": 1, "verification_evidence": 0.8, "structure_quality": 0.9}'
    assert await _signal(good).fast_reject("t", "out") is False
