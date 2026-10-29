"""D4: `skill compare` runs a skill's with-and-without A/B through ComparisonRunner.

ComparisonRunner had no caller, and its `flow_factory(session=, skill_names=)`
contract matched no factory. The CLI adapter builds each run on the container's
target flow factory: the "with" run gets only the named skill as its skill prompt,
the "without" run gets none, and skill retrieval is off for both so nothing else
leaks into either side.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from click.testing import CliRunner


def test_the_adapter_loads_only_the_named_skill():
    from cli.commands.skills import _ab_flow_factory

    calls = []
    registry = SimpleNamespace(build_system_prompt_extensions=lambda names: f"skills:{names}")

    def base(session, **kwargs):
        calls.append(kwargs)
        return "flow"

    factory = _ab_flow_factory(registry, base)
    factory(session="s1", skill_names=["deploy"])
    factory(session="s2", skill_names=[])
    assert calls[0] == {"skill_prompt": "skills:['deploy']", "skill_retrieval": False}
    assert calls[1] == {"skill_prompt": None, "skill_retrieval": False}


def test_the_target_factory_takes_a_skill_prompt_and_can_skip_retrieval():
    import inspect

    from weebot.application.di._skillopt import SkillOptMixin

    src = inspect.getsource(SkillOptMixin._create_target_flow_factory)
    assert "skill_prompt=skill_prompt" in src
    assert "if skill_retrieval" in src


def test_skill_compare_prints_the_comparison(monkeypatch):
    from cli.commands import skills as module
    from weebot.application.harness.comparison_runner import ComparisonReport, ComparisonResult

    report = ComparisonReport(skill_name="deploy")
    report.results.append(
        ComparisonResult(
            run_with="a", run_without="b", score_with=0.9, score_without=0.4, delta=0.5, passed=True
        )
    )

    async def fake_compare(skill_name, prompts, expected):
        assert (skill_name, prompts, expected) == ("deploy", ["do it"], None)
        return report

    monkeypatch.setattr(module, "_compare", fake_compare)
    monkeypatch.setattr(module, "_loaded_registry", lambda: MagicMock())
    result = CliRunner().invoke(module.skill, ["compare", "deploy", "-p", "do it"])
    assert result.exit_code == 0, result.output
    assert "+0.50" in result.output


def test_an_unknown_skill_is_refused(monkeypatch):
    from cli.commands import skills as module

    registry = MagicMock()
    registry.get.return_value = None
    monkeypatch.setattr(module, "_loaded_registry", lambda: registry)
    result = CliRunner().invoke(module.skill, ["compare", "nope", "-p", "x"])
    assert result.exit_code != 0 and "nope" in result.output
