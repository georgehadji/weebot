#!/usr/bin/env python3
"""Ratchet for the total number of ruff violations at the repo's own config.

Phase 0.3 of ``tasks/specs/arch_audit_2026_10_remediation_plan.md`` (CI-1).

CI's blocking ruff step selects only ``F821,E9`` (undefined names, syntax
errors), so every other rule the repo configured in ``pyproject.toml`` reported
into the void. ``lint_unused_locals.py`` ratchets one rule (F841); this ratchets
the whole configured set, so a new violation of any kind fails the build
without making the 700-odd existing ones a blocker.

Same bidirectional contract as the other ratchets: fails above the ceiling and
below it. Same honest fragility as ``lint_unused_locals.py``: the count is what
a third-party tool reports, so a ruff upgrade can move it with no code change.
The version is printed with every count.

Usage:
    python scripts/lint_ruff_violations.py
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_TARGETS = ["weebot/", "cli/"]
_FOUND = re.compile(r"^Found (\d+) errors?\.", re.MULTILINE)


def _ceiling_check(actual: int) -> tuple[int, str]:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from quality_ceilings import check

    return check("ruff_violations", actual)


def count_violations() -> tuple[int, str]:
    """``(violations, ruff version)``. Raises RuntimeError on a tool failure."""
    version = subprocess.run(
        [sys.executable, "-m", "ruff", "--version"], capture_output=True, text=True, cwd=_ROOT
    ).stdout.strip()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "ruff", "check", *_TARGETS, "--statistics", "--no-cache"],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=_ROOT,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ruff is not installed") from exc
    # ruff exits 1 when it finds anything, which is the normal case here.
    if proc.returncode > 1:
        raise RuntimeError(f"ruff failed (exit {proc.returncode}):\n{proc.stderr}")
    match = _FOUND.search(proc.stdout)
    if match:
        return int(match.group(1)), version
    if proc.returncode == 0:
        return 0, version
    raise RuntimeError(f"could not read ruff's summary:\n{proc.stdout[-400:]}")


def main() -> int:
    print("=== ruff violations at the configured rules (ratcheted) ===")
    try:
        actual, version = count_violations()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"ruff {version}")
    status, message = _ceiling_check(actual)
    print(message, file=sys.stderr if status else sys.stdout)
    if status:
        print(
            "If this moved without a code change, check the ruff version above before\n"
            "touching the ceiling. `ruff check weebot cli --statistics` shows which rule."
        )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
