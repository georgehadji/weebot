"""Unit tests for the harness baseline snapshot and comparison logic.

These cover the pure logic only — no LLM, no network, no flow execution — so
the regression gate itself is verifiable in CI even when eval runs are not.
"""
from __future__ import annotations

import json

import pytest

from weebot.application.harness.baseline import (
    HELD_IN,
    HELD_OUT,
    SCHEMA_VERSION,
    Baseline,
    TaskOutcome,
    compare,
    load_eval_tasks,
    prompt_fingerprint,
)


def _outcome(task_id, passed, *, split=HELD_IN, fp="abc123", score=None):
    return TaskOutcome(
        task_id=task_id,
        split=split,
        fingerprint=fp,
        passed=passed,
        score=score if score is not None else (1.0 if passed else 0.0),
    )


def _baseline(*outcomes, **kw):
    return Baseline(
        recorded_at=kw.get("recorded_at", "2026-07-29T00:00:00Z"),
        git_sha=kw.get("git_sha", "deadbee"),
        model=kw.get("model", "test-model"),
        harness_version=kw.get("harness_version", "0.2.0"),
        outcomes=tuple(outcomes),
    )


class TestPromptFingerprint:
    def test_stable_across_calls(self):
        assert prompt_fingerprint("do the thing") == prompt_fingerprint("do the thing")

    def test_ignores_surrounding_whitespace(self):
        assert prompt_fingerprint("  task\n") == prompt_fingerprint("task")

    def test_differs_on_edit(self):
        assert prompt_fingerprint("task a") != prompt_fingerprint("task b")


class TestBaselineAggregates:
    def test_pass_rate(self):
        b = _baseline(_outcome("t0", True), _outcome("t1", False))
        assert b.pass_rate == 0.5

    def test_empty_baseline_is_zero_not_error(self):
        assert _baseline().pass_rate == 0.0

    def test_split_rates_are_independent(self):
        b = _baseline(
            _outcome("held_in-00", True, split=HELD_IN),
            _outcome("held_in-01", True, split=HELD_IN),
            _outcome("held_out-00", False, split=HELD_OUT),
        )
        assert b.held_in_pass_rate == 1.0
        assert b.held_out_pass_rate == 0.0
        assert b.pass_rate == pytest.approx(2 / 3)


class TestSerialization:
    def test_roundtrip_preserves_outcomes(self):
        b = _baseline(
            _outcome("held_in-00", True, fp="aaa"),
            _outcome("held_out-00", False, split=HELD_OUT, fp="bbb"),
        )
        restored = Baseline.from_dict(json.loads(json.dumps(b.to_dict())))
        assert restored.outcomes == b.outcomes
        assert restored.git_sha == b.git_sha
        assert restored.pass_rate == b.pass_rate

    def test_save_and_load(self, tmp_path):
        b = _baseline(_outcome("held_in-00", True))
        path = b.save(tmp_path / "nested" / "baseline.json")
        assert path.exists()
        assert Baseline.load(path).outcomes == b.outcomes

    def test_load_missing_file_names_the_fix(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="baseline record"):
            Baseline.load(tmp_path / "nope.json")

    def test_schema_version_mismatch_rejected(self):
        d = _baseline(_outcome("t0", True)).to_dict()
        d["schema_version"] = SCHEMA_VERSION + 1
        with pytest.raises(ValueError, match="schema version"):
            Baseline.from_dict(d)

    def test_error_field_omitted_when_absent(self):
        assert "error" not in _outcome("t0", True).to_dict()

    def test_error_field_survives_roundtrip(self):
        o = TaskOutcome("t0", HELD_IN, "aaa", False, 0.0, error="boom")
        assert TaskOutcome.from_dict(o.to_dict()).error == "boom"


class TestCompare:
    def test_identical_run_is_ok(self):
        b = _baseline(_outcome("t0", True), _outcome("t1", False))
        c = compare(b, [_outcome("t0", True), _outcome("t1", False)])
        assert c.ok
        assert c.regressions == ()
        assert c.unchanged == 2
        assert c.delta == 0.0

    def test_detects_regression(self):
        b = _baseline(_outcome("t0", True), _outcome("t1", True))
        c = compare(b, [_outcome("t0", True), _outcome("t1", False)])
        assert not c.ok
        assert len(c.regressions) == 1
        assert c.regressions[0].task_id == "t1"
        assert c.regressions[0].was is True and c.regressions[0].now is False

    def test_detects_improvement_and_stays_ok(self):
        b = _baseline(_outcome("t0", False))
        c = compare(b, [_outcome("t0", True)])
        assert c.ok
        assert len(c.improvements) == 1
        assert c.delta == 1.0

    def test_offsetting_flips_hold_rate_and_pass(self):
        """One task regresses, another improves — aggregate rate is flat.

        This is the case the aggregate gate exists for: stochastic runs shuffle
        which tasks pass without the agent getting worse overall.
        """
        b = _baseline(_outcome("t0", True), _outcome("t1", False))
        c = compare(b, [_outcome("t0", False), _outcome("t1", True)])
        assert c.delta == 0.0
        assert c.ok
        # ...but the flip is still surfaced for diagnosis.
        assert len(c.regressions) == 1
        assert len(c.improvements) == 1

    def test_tolerance_permits_small_drop(self):
        b = _baseline(*[_outcome(f"t{i}", True) for i in range(10)])
        fresh = [_outcome(f"t{i}", i != 0) for i in range(10)]  # 9/10
        assert not compare(b, fresh, tolerance=0.0).ok
        assert compare(b, fresh, tolerance=0.1).ok

    def test_tolerance_does_not_permit_large_drop(self):
        b = _baseline(*[_outcome(f"t{i}", True) for i in range(10)])
        fresh = [_outcome(f"t{i}", i > 4) for i in range(10)]  # 5/10
        assert not compare(b, fresh, tolerance=0.1).ok

    def test_drifted_prompt_fails_even_when_passing(self):
        """A rewritten prompt must not be silently compared as the same task."""
        b = _baseline(_outcome("t0", True, fp="original"))
        c = compare(b, [_outcome("t0", True, fp="edited")])
        assert c.drifted == ("t0",)
        assert not c.ok
        # Not counted as a regression or an improvement — it is incomparable.
        assert c.regressions == ()
        assert c.improvements == ()

    def test_missing_task_fails(self):
        b = _baseline(_outcome("t0", True), _outcome("t1", True))
        c = compare(b, [_outcome("t0", True)])
        assert c.missing == ("t1",)
        assert not c.ok

    def test_added_task_is_reported_but_not_fatal(self):
        b = _baseline(_outcome("t0", True))
        c = compare(b, [_outcome("t0", True), _outcome("t1", True)])
        assert c.added == ("t1",)
        assert c.ok

    def test_blank_fingerprints_skip_drift_check(self):
        """Baselines recorded before fingerprinting still compare."""
        b = _baseline(_outcome("t0", True, fp=""))
        c = compare(b, [_outcome("t0", False, fp="")])
        assert c.drifted == ()
        assert len(c.regressions) == 1

    def test_summary_mentions_regressions(self):
        b = _baseline(_outcome("t0", True))
        text = compare(b, [_outcome("t0", False)]).summary()
        assert "REGRESSION" in text
        assert "t0" in text


class TestLoadEvalTasks:
    def test_loads_both_splits_with_stable_ids(self, tmp_path):
        p = tmp_path / "eval_tasks.yaml"
        p.write_text(
            "held_in_tasks:\n  - 'first'\n  - 'second'\n"
            "held_out_tasks:\n  - 'third'\n",
            encoding="utf-8",
        )
        tasks = load_eval_tasks(p)
        assert [t[0] for t in tasks] == ["held_in-00", "held_in-01", "held_out-00"]
        assert [t[1] for t in tasks] == [HELD_IN, HELD_IN, HELD_OUT]
        assert tasks[2][2] == "third"

    def test_missing_keys_yield_empty(self, tmp_path):
        p = tmp_path / "eval_tasks.yaml"
        p.write_text("held_in_tasks:\n", encoding="utf-8")
        assert load_eval_tasks(p) == []

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_eval_tasks(tmp_path / "absent.yaml")

    def test_repo_eval_tasks_parse(self):
        """The committed eval_tasks.yaml must actually load."""
        from pathlib import Path

        repo_tasks = Path("weebot/config/harness/eval_tasks.yaml")
        if not repo_tasks.exists():
            pytest.skip("eval_tasks.yaml not present")
        tasks = load_eval_tasks(repo_tasks)
        assert len(tasks) >= 2
        assert all(prompt.strip() for _, _, prompt in tasks)
        assert len({t[0] for t in tasks}) == len(tasks), "task IDs must be unique"
