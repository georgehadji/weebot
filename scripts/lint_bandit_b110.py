#!/usr/bin/env python3
"""Ratchet for bandit's B110 (try/except/pass) findings.

The workflow previously ran bandit as ``bandit ... || echo "(non-blocking)"``.
Every finding was therefore discarded and the step's exit code was a constant,
which made the whole ``security-scan`` job incapable of failing: all three of
its steps swallowed their own result the same way. A required check built on
that job would have gated nothing.

Enforced as a **bidirectional** ratchet (phase B2): the run fails when the count
exceeds the ceiling in ``tasks/quality/ceilings.toml`` *and* when it falls below
it. The second half is the point -- a ceiling that only blocks upward movement
sits where it was first measured forever, and the slack between actual and
ceiling is exactly where a regression hides unnoticed. Lower the ceiling in the
same commit that removes the debt; it may never be raised.

Not the same metric as ``lint_except_pass.py``. That script counts handlers
whose body is exactly ``pass`` or ``...``; bandit's B110 is its own detection
of try/except/pass. The sets overlap heavily but are not equal (139 against
68 at the time of writing), so the two ceilings move independently -- which is
why they are two separate entries in ``tasks/quality/ceilings.toml``.

Exit code: 0 only when count == ceiling.

Usage:
    python scripts/lint_bandit_b110.py
"""
from __future__ import annotations

import json
import subprocess
import sys

# The ceiling lives in tasks/quality/ceilings.toml (phase B2); it was a constant
# here. Measured on 3fd25df -- the workflow comment claimed 71, the actual is 68.


def _ceiling_check(actual: int) -> tuple[int, str]:
    import pathlib as _p

    sys.path.insert(0, str(_p.Path(__file__).resolve().parent))
    from quality_ceilings import check

    return check("bandit_b110", actual)

_CMD = [
    sys.executable, "-m", "bandit",
    "-c", "pyproject.toml",
    "-r", "weebot/", "cli/",
    "-f", "json", "-q",
]


def main() -> int:
    try:
        proc = subprocess.run(_CMD, capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        print("bandit is not installed; cannot evaluate the B110 ratchet.", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print("bandit timed out after 600s.", file=sys.stderr)
        return 1

    # bandit exits 1 when it reports findings, which is the normal case here.
    # An unparseable stdout means bandit itself failed, and that must not be
    # mistaken for "no findings" -- the failure mode this script exists to end.
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print("bandit produced no parseable JSON report:", file=sys.stderr)
        print((proc.stderr or proc.stdout or "<no output>")[:2000], file=sys.stderr)
        return 1

    findings = [r for r in report.get("results", []) if r.get("test_id") == "B110"]
    count = len(findings)

    print("=== bandit B110 (try/except/pass) ratchet ===")
    code, message = _ceiling_check(count)
    print(message)

    if code and count > 0:
        for f in findings[:20]:
            print(f"  {f.get('filename')}:{f.get('line_number')}")
        if count > 20:
            print(f"  ... and {count - 20} more")
        print("Log the exception, or re-raise.", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
