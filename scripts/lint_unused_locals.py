#!/usr/bin/env python3
"""Ratchet for ruff's F841 (local assigned but never used).

This gate exists because the same defect was found twice in one session, and
both times the linter had been reporting it all along:

    weebot/qmd_integration/mcp_client.py:239   proc = subprocess.Popen(...)
        The MCP HTTP server was bound to a local, so `close()` could not
        reach it. Every start leaked a server holding the port.

    weebot/application/flows/states/executing.py:382   effective_prompt = ...
        Phase 5 polled the steering channel, logged "Steering received for
        session %s" at INFO, formatted the user's message into an augmented
        prompt -- and sent the ORIGINAL. Mid-execution steering was collected,
        acknowledged, and discarded.

CI runs `ruff check weebot/ cli/ --select F821,E9`. F841 was never in the
selector, so ruff could see both and the gate did not ask. That is the
fail-open shape this audit keeps finding, this time in the tooling.

An unused local is not always a defect -- a placeholder, an unpacked tuple, a
deliberately-ignored return. But it is always *work the author wrote and the
program does not do*, which is why it deserves a ceiling rather than a blanket
ban: the 33 that exist are an inventory to triage, and no new one may join
them.

Enforced as a **bidirectional** ratchet: the run fails when the count exceeds
the ceiling AND when it falls below it. See tasks/quality/ceilings.toml for
why the second half is the point.

ONE HONEST FRAGILITY, stated rather than hidden: this ratchet counts what a
third-party tool reports, and `requirements.txt` pins only `ruff>=0.8.0`. A
ruff upgrade that changes F841's detection changes this number with no code
change. The version is printed with every count so that a surprise is legible,
and the failure message says to check it before touching the ceiling.

Exit code: 0 only when count == ceiling.

Usage:
    python scripts/lint_unused_locals.py
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_TARGETS = ["weebot/", "cli/"]


def _ceiling_check(actual: int) -> tuple[int, str]:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from quality_ceilings import check

    return check("unused_locals", actual)


def _ruff_version() -> str:
    try:
        out = subprocess.run(
            [sys.executable, "-m", "ruff", "--version"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def main() -> int:
    print("=== unused local variables (ruff F841, ratcheted) ===")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "ruff", "check", *_TARGETS,
             "--select", "F841", "--output-format", "concise", "--no-cache"],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=_ROOT,
        )
    except FileNotFoundError:
        print("ruff is not installed; cannot evaluate the F841 ratchet.", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print("ruff timed out; cannot evaluate the F841 ratchet.", file=sys.stderr)
        return 1

    # ruff exits 1 when it finds anything, which is the normal case here.
    # An exit code above 1 is a real tool failure and must not read as clean.
    if proc.returncode > 1:
        print(f"ruff failed (exit {proc.returncode}):\n{proc.stderr}", file=sys.stderr)
        return 1

    findings = [line for line in proc.stdout.splitlines() if ": F841 " in line]
    for line in findings[-3:]:
        print(f"  {line}")
    if len(findings) > 3:
        print(f"  ... and {len(findings) - 3} more")

    print(f"\nruff {_ruff_version()}")
    status, message = _ceiling_check(len(findings))
    print(message)
    if status != 0:
        print(
            "If this count moved without a code change, check the ruff version "
            "above before touching the ceiling."
        )
        print("An unused local is work the author wrote and the program does not do.")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
