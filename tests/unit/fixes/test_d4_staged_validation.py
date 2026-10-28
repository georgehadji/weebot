"""D4: SkillOpt validation probes a few tasks first (WEEBOT_STAGED_VALIDATION).

StagedEvaluator implements probe-then-full evaluation but had no caller, so every
candidate skill ran its whole held-out set. With it, a candidate that scores below
the threshold on the probe stops there; one that passes runs the rest, and no task
runs twice.
"""

from collections import Counter
from types import SimpleNamespace

from weebot.application.services.staged_evaluator import StagedEvaluator
from weebot.application.services.validation_runner import ValidationRunner


def _runner(score_by_task: dict[str, float], staged=None):
    runs = Counter()

    def flow_factory(session):
        task = session.context["last_prompt"]

        async def run(_prompt):
            runs[task] += 1
            if False:
                yield None

        return SimpleNamespace(run=run, _session=session)

    async def scoring_fn(session):
        return score_by_task[session.context["last_prompt"]]

    runner = ValidationRunner(
        task_runner=None, flow_factory=flow_factory, scoring_fn=scoring_fn, staged=staged
    )
    return runner, runs


_TASKS = [f"t{i}" for i in range(6)]


async def test_a_failed_probe_stops_the_run():
    runner, runs = _runner(dict.fromkeys(_TASKS, 0.0), StagedEvaluator(probe_size=2, threshold=0.3))
    result = await runner.validate("skill", _TASKS, baseline_score=0.5)
    assert set(runs) == {"t0", "t1"}
    assert result.passed is False and result.details["tasks_skipped"] == 4


async def test_a_passed_probe_runs_every_task_once():
    runner, runs = _runner(dict.fromkeys(_TASKS, 0.9), StagedEvaluator(probe_size=2, threshold=0.3))
    result = await runner.validate("skill", _TASKS, baseline_score=0.5)
    assert runs == Counter(dict.fromkeys(_TASKS, 1))
    assert result.passed and result.n_tasks == 6


async def test_without_a_stager_every_task_runs():
    runner, runs = _runner(dict.fromkeys(_TASKS, 0.0))
    await runner.validate("skill", _TASKS, baseline_score=0.5)
    assert set(runs) == set(_TASKS)


def test_skillopt_builds_the_stager_only_when_its_flag_is_on(monkeypatch):
    import importlib
    import inspect

    import weebot.config.feature_flags as flags
    from weebot.application.di._skillopt import SkillOptMixin

    monkeypatch.delenv("WEEBOT_STAGED_VALIDATION", raising=False)
    importlib.reload(flags)
    assert flags.STAGED_VALIDATION_ENABLED is False
    src = inspect.getsource(SkillOptMixin)
    assert "STAGED_VALIDATION_ENABLED" in src and "StagedEvaluator()" in src
