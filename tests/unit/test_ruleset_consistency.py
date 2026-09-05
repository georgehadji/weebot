"""Protection-as-code must stay honest in both directions.

Phase A2 of tasks/specs/review_gate_and_residual_work_plan.md.

Two scripts are under test and they fail in opposite ways, so they are proven
separately:

``check_ruleset_consistency`` is offline and blocking. It exists because GitHub
validates required-check names against nothing: a renamed job leaves the
ruleset requiring a context that no check ever reports, and every pull request
then waits on it forever with no error anywhere explaining why.

``check_branch_protection`` talks to the API, so the thing worth proving is its
decision table rather than its plumbing. Its one invariant -- **exit 0 only on
a verified match** -- is asserted here against every other outcome, because a
drift detector that passes when it cannot see would be the same fail-open
control the V7 hunt spent nine waves removing.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import pathlib

import pytest

yaml = pytest.importorskip("yaml")

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


consistency = _load("check_ruleset_consistency")
protection = _load("check_branch_protection")


def _rule(ruleset: dict, rule_type: str) -> dict:
    """Address a rule by type. Indexing by position breaks confusingly on a reorder."""
    return next(r for r in ruleset["rules"] if r["type"] == rule_type)


@pytest.fixture
def ruleset() -> dict:
    return json.loads((_ROOT / ".github" / "rulesets" / "main.json").read_text(encoding="utf-8"))


@pytest.fixture
def workflow() -> dict:
    return yaml.safe_load(
        (_ROOT / ".github" / "workflows" / "architecture.yml").read_text(encoding="utf-8")
    )


class TestTheRepositoryAgreesWithItself:
    def test_ruleset_and_workflow_are_consistent_now(self, ruleset, workflow):
        assert consistency.check(ruleset, workflow) == []

    def test_the_advisory_job_is_not_required(self, ruleset):
        """Its only blocking step is `pip install`.

        Requiring it would block merges on a package-index outage while still
        never blocking on a CVE -- strictly worse than not requiring it.
        """
        assert "Security Scan (advisory)" not in consistency.required_contexts(ruleset)

    def test_every_required_context_is_a_real_job_name(self, ruleset, workflow):
        names = {j.get("name") or jid for jid, j in workflow["jobs"].items()}
        assert set(consistency.required_contexts(ruleset)) <= names


class TestDriftBetweenTheTwoFiles:
    def test_renaming_a_job_is_caught(self, ruleset, workflow):
        workflow["jobs"]["unit-tests"]["name"] = "Unit tests"
        problems = consistency.check(ruleset, workflow)
        assert any("matches no job" in p for p in problems)
        assert any("not a required check" in p for p in problems)

    def test_a_new_failable_job_must_be_required(self, ruleset, workflow):
        workflow["jobs"]["mutation-tests"] = {
            "name": "Mutation Tests",
            "steps": [{"name": "Run", "run": "pytest --mutate"}],
        }
        problems = consistency.check(ruleset, workflow)
        assert any("'Mutation Tests'" in p and "not a required check" in p for p in problems)

    def test_a_new_advisory_job_need_not_be_required(self, ruleset, workflow):
        workflow["jobs"]["perf"] = {
            "name": "Benchmarks (advisory)",
            "steps": [{"name": "Run", "run": "pytest --benchmark", "continue-on-error": True}],
        }
        assert consistency.check(ruleset, workflow) == []

    def test_requiring_an_advisory_job_is_caught(self, ruleset, workflow):
        _rule(ruleset, "required_status_checks")["parameters"][
            "required_status_checks"
        ].append({"context": "Security Scan (advisory)"})
        problems = consistency.check(ruleset, workflow)
        assert any("is an advisory job" in p for p in problems)

    @pytest.mark.parametrize("rule_type", ["deletion", "non_fast_forward"])
    def test_dropping_a_structural_rule_is_caught(self, ruleset, workflow, rule_type):
        """Required checks are trivially bypassable if main can be force-pushed."""
        ruleset["rules"] = [r for r in ruleset["rules"] if r.get("type") != rule_type]
        problems = consistency.check(ruleset, workflow)
        assert any(rule_type in p and "missing" in p for p in problems)

    def test_evaluate_only_enforcement_is_caught(self, ruleset, workflow):
        ruleset["enforcement"] = "evaluate"
        problems = consistency.check(ruleset, workflow)
        assert any("does not block" in p for p in problems)

    def test_requiring_a_job_that_cannot_fail_is_caught(self, ruleset, workflow):
        """A job whose every real step is advisory has a constant conclusion."""
        workflow["jobs"]["unit-tests"]["steps"] = [
            {"name": "Install dependencies", "run": "pip install -r requirements.txt"},
            {"name": "Run tests", "run": "pytest", "continue-on-error": True},
        ]
        problems = consistency.check(ruleset, workflow)
        assert any("gates nothing" in p for p in problems)

    def test_setup_alone_does_not_make_a_job_failable(self):
        job = {"steps": [{"name": "Install dependencies", "run": "pip install -r req.txt"}]}
        assert consistency.job_can_fail(job) is False


class TestDriftAgainstTheLiveRepository:
    """`evaluate` is the decision table. Only one branch of it may return 0."""

    @pytest.fixture
    def live(self, ruleset) -> dict:
        return copy.deepcopy(ruleset)

    def test_an_exact_match_passes(self, ruleset, live):
        code, msg = protection.evaluate(200, [live], ruleset, "main")
        assert code == 0
        assert "matches" in msg

    def test_extra_api_only_fields_do_not_count_as_drift(self, ruleset, live):
        live.update({"id": 1234, "source": "georgehadji/weebot", "created_at": "2026-09-05"})
        assert protection.evaluate(200, [live], ruleset, "main")[0] == 0

    def test_a_dropped_required_check_is_drift(self, ruleset, live):
        params = _rule(live, "required_status_checks")["parameters"]
        params["required_status_checks"] = params["required_status_checks"][:-1]
        code, msg = protection.evaluate(200, [live], ruleset, "main")
        assert code == 1
        assert "no longer required" in msg

    def test_a_dropped_rule_is_drift(self, ruleset, live):
        live["rules"] = [r for r in live["rules"] if r.get("type") != "non_fast_forward"]
        code, msg = protection.evaluate(200, [live], ruleset, "main")
        assert code == 1
        assert "non_fast_forward" in msg

    def test_downgrading_enforcement_is_drift(self, ruleset, live):
        live["enforcement"] = "evaluate"
        code, msg = protection.evaluate(200, [live], ruleset, "main")
        assert code == 1
        assert "enforcement" in msg

    def test_an_added_bypass_actor_is_drift(self, ruleset, live):
        live["bypass_actors"] = [{"actor_id": 5, "actor_type": "Integration"}]
        code, msg = protection.evaluate(200, [live], ruleset, "main")
        assert code == 1
        assert "bypass" in msg

    def test_a_missing_ruleset_is_drift_not_an_error(self, ruleset):
        code, msg = protection.evaluate(200, [], ruleset, "main")
        assert code == 1
        assert "no ruleset named" in msg

    def test_a_renamed_ruleset_does_not_silently_pass(self, ruleset, live):
        live["name"] = "main-old"
        assert protection.evaluate(200, [live], ruleset, "main")[0] == 1

    @pytest.mark.parametrize("status", [401, 403, 404, 422, 500, 502, 503])
    def test_no_error_status_is_ever_treated_as_a_pass(self, status, ruleset):
        """The whole point. "I could not check" must never read as "nothing is wrong"."""
        code, msg = protection.evaluate(status, {}, ruleset, "main")
        assert code == 1, f"HTTP {status} was treated as a pass"
        assert "DRIFT" in msg or "CANNOT VERIFY" in msg

    def test_a_permission_error_names_the_remedy(self, ruleset):
        _, msg = protection.evaluate(403, {}, ruleset, "main")
        assert "PROTECTION_READ_TOKEN" in msg

    def test_a_garbage_payload_does_not_crash_into_a_pass(self, ruleset):
        for body in ("not json", 42, None, [None], [{"unrelated": True}]):
            code, _ = protection.evaluate(200, body, ruleset, "main")
            assert code == 1, f"payload {body!r} was treated as a pass"
