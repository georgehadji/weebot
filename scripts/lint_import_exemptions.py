#!/usr/bin/env python3
"""Count the reviewed exemptions in .importlinter, as a bidirectional ratchet.

Phase 3.4 of ``tasks/specs/arch_audit_2026_09_remediation_plan.md``.

Each ``ignore_imports`` entry is an edge a contract would otherwise forbid.
The count had only ever been tracked in prose, and the prose targets moved
the wrong way: ADR-001 recorded 52, ARCHITECTURE.md D3 recorded 35 against a
target of <=25, and the file held 67 -- measured per commit from git, rising
53 -> 67 over six weeks with a peak of 72. A number in a markdown file is not
a gate.

Enforced like the other ratchets: the run fails when the count exceeds the
ceiling in ``tasks/quality/ceilings.toml`` *and* when it falls below it. Lower
the ceiling in the commit that removes an exemption.

Exit code: 0 only when count == ceiling.

Usage:
    python scripts/lint_import_exemptions.py
"""

from __future__ import annotations

import configparser
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CONFIG = _ROOT / ".importlinter"


def count_exemptions() -> dict[str, int]:
    """``{contract id: active ignore_imports entries}``. Comments do not count."""
    parser = configparser.ConfigParser()
    parser.optionxform = str  # keep case
    parser.read(_CONFIG, encoding="utf-8")
    counts: dict[str, int] = {}
    for section in parser.sections():
        if not section.startswith("importlinter:contract:"):
            continue
        raw = parser[section].get("ignore_imports", "")
        entries = [
            line.strip()
            for line in raw.splitlines()
            if "->" in line and not line.strip().startswith("#")
        ]
        counts[section.split(":", 2)[-1]] = len(entries)
    return counts


def _ceiling_check(actual: int) -> tuple[int, str]:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from quality_ceilings import check

    return check("import_exemptions", actual)


def main(argv: list[str]) -> int:
    counts = count_exemptions()
    for contract, n in sorted(counts.items()):
        print(f"{contract:24s} {n:3d}")
    code, message = _ceiling_check(sum(counts.values()))
    print(f"\n{message}")
    if code:
        print(
            "Remove the violation rather than exempting it, or -- if an exemption\n"
            "was removed -- lower `import_exemptions` in tasks/quality/ceilings.toml.",
            file=sys.stderr,
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
