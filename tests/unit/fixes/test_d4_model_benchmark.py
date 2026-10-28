"""D4: `benchmark model ID` measures a model and saves its quality profile.

BenchmarkRunner was the missing producer for the model router's quality profiles:
`save_benchmark_profile` had no caller. Two defects came with it. A saved benchmark
replaced the model's whole seed profile, so the seeded axes the suites do not
measure (legal, citation, planning) dropped to nothing; and the results file was
written inside the installed package.
"""

import json
from types import SimpleNamespace

from click.testing import CliRunner

from weebot.config import capability_profiles as profiles
from weebot.domain.models.capability import CapabilityAxis, ModelQualityProfile


def _use_files(monkeypatch, tmp_path, seeds: str, benchmarks: dict | None):
    seed_file = tmp_path / "seeds.yaml"
    seed_file.write_text(seeds, encoding="utf-8")
    bench_file = tmp_path / "bench.json"
    if benchmarks is not None:
        bench_file.write_text(json.dumps(benchmarks), encoding="utf-8")
    monkeypatch.setattr(profiles, "_PROFILES_PATH", seed_file)
    monkeypatch.setattr(profiles, "_BENCHMARK_PATH", bench_file)
    profiles.refresh()


def test_a_benchmark_keeps_the_seeded_axes_it_did_not_measure(monkeypatch, tmp_path):
    seeds = "m1:\n  axes: {reasoning: 5, legal: 9}\n"
    measured = {"m1": {"axes": {"reasoning": 8}, "source": "benchmark"}}
    _use_files(monkeypatch, tmp_path, seeds, measured)
    try:
        axes = profiles.get_profile("m1").axes
        assert axes[CapabilityAxis.REASONING] == 8.0
        assert axes[CapabilityAxis.LEGAL] == 9.0
    finally:
        profiles.refresh()


def test_the_results_file_is_not_inside_the_package():
    package_dir = profiles._PROFILES_PATH.parent
    assert package_dir not in profiles._BENCHMARK_PATH.parents


def test_benchmark_model_runs_the_suites_and_saves_the_profile(monkeypatch):
    from cli.commands import harness as module

    saved = []
    profile = ModelQualityProfile(
        model_id="m1", axes={CapabilityAxis.CODING: 7.0}, source="benchmark"
    )

    class _Runner:
        def __init__(self, call_llm, cost_ceiling):
            self.ceiling = cost_ceiling

        async def run(self, model_id):
            assert model_id == "m1"
            return profile

    monkeypatch.setattr("weebot.infrastructure.benchmark.runner.BenchmarkRunner", _Runner)
    monkeypatch.setattr(profiles, "save_benchmark_profile", saved.append)
    monkeypatch.setattr(
        "weebot.interfaces.factories.shared_container",
        lambda: SimpleNamespace(get=lambda key: SimpleNamespace(chat=None)),
    )
    result = CliRunner().invoke(module.benchmark, ["model", "m1"])
    assert result.exit_code == 0, result.output
    assert saved == [profile]
    assert "coding" in result.output
