"""A CI job that cannot fail must not be mistaken for a gate.

Part A of tasks/specs/review_gate_and_residual_work_plan.md. The workflow had
seven steps ending in ``|| echo``, and all three steps of the ``Security Scan``
job did, so that job's conclusion was a constant: it reported success whatever
its scanners found. Naming it as a required check would have gated nothing.

That is the C2 (fail-open control) class from the V7 defect hunt, expressed in
CI configuration rather than in Python, and it is why the plan's ordering is
*repair the instrument, then require it*.

These tests are the ratchet for that repair. They parse the workflow rather
than grepping it, so a comment mentioning the old idiom does not trip them.
"""

from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

_WORKFLOW = (
    pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows" / "architecture.yml"
)

# Shell idioms that discard a command's exit code. `continue-on-error: true` is
# the supported way to say "advisory": it keeps the real exit code and surfaces
# the step as a warning, instead of forging a success.
_SWALLOWING = ("|| echo", "|| true", "|| :")


def _workflow() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def _named_steps(job: dict) -> list[dict]:
    return [s for s in job.get("steps", []) if s.get("name")]


def _is_advisory(step: dict) -> bool:
    return bool(step.get("continue-on-error"))


class TestNoStepSwallowsItsExitCode:
    def test_the_workflow_parses(self):
        """Guard the guard: an unparseable workflow would make everything below vacuous."""
        jobs = _workflow().get("jobs", {})
        assert len(jobs) >= 8, f"expected the full job set, got {sorted(jobs)}"

    def test_no_run_step_discards_its_result(self):
        """Scans every workflow, not only the one this repair audited.

        A step that swallows its exit code is dishonest wherever it lives, and
        a new workflow file is exactly where the idiom would come back.
        """
        offenders = []
        for path in sorted(_WORKFLOW.parent.glob("*.yml")):
            parsed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for job_id, job in (parsed.get("jobs") or {}).items():
                for step in job.get("steps", []):
                    run = step.get("run") or ""
                    for idiom in _SWALLOWING:
                        if idiom in run:
                            offenders.append(
                                f"{path.name} / {job_id} / "
                                f"{step.get('name', '<unnamed>')}: {idiom}"
                            )
        assert offenders == [], (
            "these steps discard their exit code, so their job cannot fail on them. "
            "Use `continue-on-error: true` to mark a step advisory — it keeps the "
            "exit code and reports honestly.\n" + "\n".join(offenders)
        )


class TestAdvisoryJobsSaySo:
    """A job that cannot fail is legitimate — but its name must admit it."""

    @staticmethod
    def _can_fail(job: dict) -> bool:
        """Can the job fail *on its own subject matter*?

        `Install dependencies` is excluded deliberately, and the distinction is
        load-bearing rather than a convenience. Every job has that step, so
        counting it would make every job look blocking — including
        `Security Scan (advisory)`, whose scanners are all
        `continue-on-error`. Its only way to fail is a package-index outage:
        it blocks on infrastructure and passes on a CVE. That is precisely a
        job that must stay out of any required-checks list, so it must not
        count as blocking here.
        """
        blocking = [
            s for s in _named_steps(job)
            if not _is_advisory(s) and s.get("name") != "Install dependencies"
        ]
        return bool(blocking)

    def test_every_unfailable_job_is_named_advisory(self):
        offenders = []
        for job_id, job in _workflow()["jobs"].items():
            if self._can_fail(job):
                continue
            name = (job.get("name") or job_id).lower()
            if "advisory" not in name:
                offenders.append(f"{job_id} ({job.get('name')})")
        assert offenders == [], (
            "these jobs have no step that can fail, so their conclusion is a constant. "
            "Either give them a blocking step or put 'advisory' in the name, so nobody "
            "adds them to a required-checks list.\n" + "\n".join(offenders)
        )

    def test_a_job_named_blocking_has_something_that_blocks(self):
        for job_id, job in _workflow()["jobs"].items():
            name = (job.get("name") or job_id).lower()
            if "blocking" in name:
                assert self._can_fail(job), f"{job_id} is named blocking but cannot fail"

    def test_at_least_one_security_job_can_fail(self):
        """The split exists so that security has a gate, not only a report."""
        jobs = _workflow()["jobs"]
        security = {k: v for k, v in jobs.items() if "security" in k}
        assert security, "no security job found"
        assert any(self._can_fail(v) for v in security.values()), (
            "every security job is advisory — security has no gate at all"
        )


class TestRatchetsAreWiredIn:
    """Each ratchet script must actually be invoked by the workflow."""

    @pytest.mark.parametrize(
        "script",
        [
            "scripts/lint_except_pass.py",
            "scripts/lint_async_io.py",
            "scripts/lint_bandit_b110.py",
        ],
    )
    def test_ratchet_script_is_referenced(self, script):
        text = _WORKFLOW.read_text(encoding="utf-8")
        assert script in text, f"{script} exists but no workflow step runs it"

    def test_env_access_ratchet_is_not_disarmed(self):
        """`make lint-env-access` is a real ratchet; it was wrapped in `|| echo`."""
        for job in _workflow()["jobs"].values():
            for step in job.get("steps", []):
                run = step.get("run") or ""
                if "lint-env-access" in run:
                    assert not _is_advisory(step), (
                        "the env-access ratchet is marked advisory, which disarms it"
                    )
                    assert not any(i in run for i in _SWALLOWING)
                    return
        pytest.fail("no step runs `make lint-env-access`")
