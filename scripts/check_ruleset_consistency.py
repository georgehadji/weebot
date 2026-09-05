#!/usr/bin/env python3
"""Keep `.github/rulesets/main.json` and the CI workflow in agreement.

Phase A2 of tasks/specs/review_gate_and_residual_work_plan.md. This runs
offline: no network, no token, no repository permissions. It compares two files
that must agree but have nothing linking them, and it catches two failure modes
that are silent in GitHub's UI.

**A required context that names no job blocks every pull request forever.**
GitHub does not validate required-check names against anything. Rename a job --
"Unit Tests" to "Unit tests", say -- and the ruleset still requires the old
name. No check ever reports it, so every PR sits on "Expected -- Waiting for
status to be reported" with no error anywhere saying why. The usual fix is to
delete the protection, which is how a repository loses its gate.

**A new job that nobody adds to the ruleset is silently ungated.** CI grows a
job, the job goes red, and the merge button stays green because nothing
requires it. That is the C2 (fail-open control) class the V7 defect hunt kept
finding in Python, expressed here in configuration.

So the invariant is a two-way one, and the advisory naming convention from A1
is what makes it decidable: **the set of required contexts equals the set of
job names that do not say "advisory"**. A job that cannot fail on its own
subject matter says so in its name and is excluded; everything else is
required, and the check fails if either side drifts.

Exit code: 0 if the two files agree, 1 otherwise.

Usage:
    python scripts/check_ruleset_consistency.py
"""
from __future__ import annotations

import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_RULESET = _ROOT / ".github" / "rulesets" / "main.json"
_WORKFLOW = _ROOT / ".github" / "workflows" / "architecture.yml"

# `Install dependencies` is excluded when deciding whether a job can fail on
# its own subject matter. Every job has one and it is not the job's purpose: an
# advisory scanner whose only blocking step is `pip install` fails on a package
# index outage and passes on a CVE, which is the worst of both. Such a job must
# stay out of the required set, so it must not count as blocking here.
_SETUP_STEP_NAMES = frozenset({"Install dependencies"})

# Rules the ruleset must carry regardless of which checks are required.
# `deletion` and `non_fast_forward` are what stop main being deleted or
# rewritten; without them the required checks are trivially bypassable.
_REQUIRED_RULE_TYPES = frozenset({"deletion", "non_fast_forward", "required_status_checks"})


def job_can_fail(job: dict) -> bool:
    """True if the job has a blocking step that is not just environment setup."""
    for step in job.get("steps", []):
        if not step.get("name") or step.get("name") in _SETUP_STEP_NAMES:
            continue
        if step.get("continue-on-error"):
            continue
        if "run" in step:
            return True
    return False


def is_advisory_job(job: dict, job_id: str) -> bool:
    return "advisory" in (job.get("name") or job_id).lower()


def required_contexts(ruleset: dict) -> list[str]:
    for rule in ruleset.get("rules", []):
        if rule.get("type") == "required_status_checks":
            params = rule.get("parameters", {})
            return [c.get("context", "") for c in params.get("required_status_checks", [])]
    return []


def check(ruleset: dict, workflow: dict) -> list[str]:
    """Return a list of problems; empty means the two files agree."""
    problems: list[str] = []

    present = {r.get("type") for r in ruleset.get("rules", [])}
    for missing in sorted(_REQUIRED_RULE_TYPES - present):
        problems.append(f"ruleset is missing the `{missing}` rule")

    if ruleset.get("enforcement") != "active":
        problems.append(
            f"enforcement is {ruleset.get('enforcement')!r}, not 'active' -- "
            "an evaluate-only ruleset reports but does not block"
        )

    jobs = workflow.get("jobs", {})
    # Map check-run name -> job id. GitHub matches required contexts against the
    # job's `name:`, falling back to the job id when `name:` is absent.
    by_name = {(j.get("name") or jid): jid for jid, j in jobs.items()}

    required = required_contexts(ruleset)
    if not required:
        problems.append("the ruleset requires no status checks at all")

    for context in required:
        jid = by_name.get(context)
        if jid is None:
            problems.append(
                f"required check {context!r} matches no job in the workflow. "
                "Nothing will ever report it, so every pull request stays blocked "
                f"on it forever. Known job names: {sorted(by_name)}"
            )
            continue
        if is_advisory_job(jobs[jid], jid):
            problems.append(
                f"required check {context!r} is an advisory job. Requiring it "
                "blocks merges on its setup failing while never blocking on what "
                "it actually scans for."
            )

    expected = {name for name, jid in by_name.items() if not is_advisory_job(jobs[jid], jid)}
    for name in sorted(expected - set(required)):
        problems.append(
            f"job {name!r} can fail but is not a required check, so a red run "
            "does not block the merge. Require it, or rename it to say 'advisory'."
        )

    for name, jid in sorted(by_name.items()):
        if name in required and not job_can_fail(jobs[jid]):
            problems.append(
                f"required check {name!r} has no blocking step of its own, so its "
                "conclusion is a constant. Requiring it gates nothing."
            )

    return problems


def main() -> int:
    try:
        import yaml
    except ImportError:
        print("PyYAML is not installed; cannot parse the workflow.", file=sys.stderr)
        return 1

    try:
        ruleset = json.loads(_RULESET.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read {_RULESET}: {exc}", file=sys.stderr)
        return 1

    try:
        workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"cannot read {_WORKFLOW}: {exc}", file=sys.stderr)
        return 1

    problems = check(ruleset, workflow)

    print("=== ruleset / workflow consistency ===")
    print(f"{len(required_contexts(ruleset))} required check(s) declared in {_RULESET.name}.")

    if problems:
        for p in problems:
            print(f"  ERROR: {p}", file=sys.stderr)
        print(
            f"\n{len(problems)} problem(s). The ruleset and the workflow have drifted apart.",
            file=sys.stderr,
        )
        return 1

    print("Required checks match the workflow's failable jobs exactly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
