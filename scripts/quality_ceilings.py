#!/usr/bin/env python3
"""The one place a debt ceiling is read, and the one place the rule lives.

Phase B2 of tasks/specs/review_gate_and_residual_work_plan.md.

Before this, five ceilings lived in three places: two as `CEILING` constants in
Python scripts, two as `?=` variables in the Makefile, and one more added later.
That arrangement had three defects.

**Nothing enforced "never raise it."** The rule was a comment. A future edit
could raise a ceiling and CI would pass, silently converting the ratchet into a
rubber stamp.

**Nothing rewarded lowering it.** `lint_async_io.py` already printed *"Ceiling
can be lowered to N"* when the count dropped -- as advice, which would be
ignored indefinitely. The slack between actual and ceiling is precisely where a
regression hides, invisibly, until it reaches the top.

**And two of them could be disarmed from the environment.** `?=` in a Makefile
takes an override from the command line or the environment, so
`PRINT_CEILING=99999 make lint-no-print` passed with 143 findings. CI runs those
targets. The mechanism to switch off a gate silently was already there.

So the rule here is exact equality in both directions, and the ceilings live in
data that no environment variable can reach.

Usage:
    python scripts/quality_ceilings.py --check print_in_production --actual 143
    python scripts/quality_ceilings.py --get bandit_b110
    python scripts/quality_ceilings.py --verify-not-raised --baseline origin/main
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import tomllib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CEILINGS = _ROOT / "tasks" / "quality" / "ceilings.toml"
_REL = "tasks/quality/ceilings.toml"

OK = 0
FAIL = 1


def load(text: str | None = None) -> dict[str, int]:
    """Parse the ceilings table. Pass *text* to check a version from git."""
    raw = text if text is not None else _CEILINGS.read_text(encoding="utf-8")
    return tomllib.loads(raw)["ceilings"]


def check(name: str, actual: int, ceilings: dict[str, int] | None = None) -> tuple[int, str]:
    """Apply the bidirectional rule. Pure; the caller does the counting.

    Counting stays with whoever already does it -- the AST walkers, the greps in
    the Makefile -- so that centralising the *rule* cannot change a *number*.
    """
    table = load() if ceilings is None else ceilings
    if name not in table:
        return FAIL, (
            f"unknown ceiling {name!r}. Known: {sorted(table)}. "
            f"Add it to {_REL} rather than hard-coding a number."
        )
    ceiling = table[name]

    if actual > ceiling:
        return FAIL, (
            f"{name}: {actual} exceeds the ceiling of {ceiling} by {actual - ceiling}. "
            "New debt of this kind was added. Fix it -- do not raise the ceiling."
        )
    if actual < ceiling:
        return FAIL, (
            f"{name}: {actual} is BELOW the ceiling of {ceiling}. This is the good "
            f"direction and it must be locked in: set {name} = {actual} in {_REL}. "
            "Leaving the ceiling high turns the difference into slack where a "
            "regression can hide unnoticed."
        )
    return OK, f"{name}: {actual}, at its ceiling."


def _baseline_ceilings(ref: str) -> dict[str, int] | None:
    """Read the ceilings file as of *ref*.

    Returns None when *ref* resolves but does not contain the file -- the file
    is new, and no ceiling can have been raised relative to a file that did not
    exist. Raises when *ref* itself cannot be resolved, because then the
    baseline is genuinely unknown.

    That distinction is the whole reason this is not one `git show`: "the file
    is new" and "I could not look" produce the same exit code from git, and
    collapsing them would make an unfetched base branch read as approval.
    """
    resolved = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        capture_output=True,
        text=True,
        cwd=_ROOT,
    )
    if resolved.returncode != 0:
        raise RuntimeError(
            f"cannot resolve {ref!r}. Fetch the base branch before running the "
            "upward guard -- an unfetched baseline is not a passing one."
        )

    proc = subprocess.run(
        ["git", "show", f"{ref}:{_REL}"],
        capture_output=True,
        text=True,
        cwd=_ROOT,
    )
    if proc.returncode != 0:
        return None
    return load(proc.stdout)


def verify_not_raised(ref: str) -> tuple[int, str]:
    """Fail if any ceiling is higher than it is at *ref*."""
    try:
        before = _baseline_ceilings(ref)
    except RuntimeError as exc:
        return FAIL, f"CANNOT VERIFY: {exc}"

    now = load()
    if before is None:
        return OK, (
            f"{_REL} does not exist at {ref} -- nothing to compare, and no ceiling "
            "can have been raised relative to a file that did not exist."
        )
    raised = [
        f"{name}: {before[name]} -> {now[name]}"
        for name in sorted(now)
        if name in before and now[name] > before[name]
    ]
    if raised:
        return FAIL, (
            "these ceilings were RAISED, which is never allowed:\n  "
            + "\n  ".join(raised)
            + "\nA ratchet that can be raised is a rubber stamp. Fix the debt instead."
        )
    lowered = [
        f"{name}: {before[name]} -> {now[name]}"
        for name in sorted(now)
        if name in before and now[name] < before[name]
    ]
    added = sorted(set(now) - set(before))
    msg = f"no ceiling raised against {ref}."
    if lowered:
        msg += " Lowered: " + ", ".join(lowered) + "."
    if added:
        msg += " New: " + ", ".join(added) + "."
    return OK, msg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--get", metavar="NAME", help="print one ceiling and exit")
    parser.add_argument("--check", metavar="NAME", help="apply the rule to a measured count")
    parser.add_argument("--actual", type=int, help="the measured count, with --check")
    parser.add_argument(
        "--verify-not-raised",
        action="store_true",
        help="fail if any ceiling is higher than at --baseline",
    )
    parser.add_argument("--baseline", default="origin/main", help="git ref to compare against")
    args = parser.parse_args(argv)

    if args.get:
        table = load()
        if args.get not in table:
            print(f"unknown ceiling {args.get!r}", file=sys.stderr)
            return FAIL
        print(table[args.get])
        return OK

    if args.verify_not_raised:
        code, message = verify_not_raised(args.baseline)
        print(message, file=sys.stderr if code else sys.stdout)
        return code

    if args.check is not None:
        if args.actual is None:
            print("--check requires --actual", file=sys.stderr)
            return FAIL
        code, message = check(args.check, args.actual)
        print(message, file=sys.stderr if code else sys.stdout)
        return code

    parser.print_help()
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
