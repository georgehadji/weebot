#!/usr/bin/env python3
"""Count functions longer than 150 lines in ``weebot/``, as a bidirectional ratchet.

Phase 0.4 of ``tasks/specs/arch_audit_2026_10_remediation_plan.md`` (CPL-1).

ADR-007 recorded ``_base.py`` at ~803 lines as a target in prose, and it grew to
1180. A per-file line count would fail on every edit; a count of *long
functions* moves only when a god method is split or a new one is written, which
is the event worth a diff in ``tasks/quality/ceilings.toml``.

A function's length is ``end_lineno - lineno + 1`` of its ``def`` (decorators
and docstring included, nested functions included in their parent).

Usage:
    python scripts/lint_long_functions.py          # check against the ceiling
    python scripts/lint_long_functions.py --list   # print each offender
"""

from __future__ import annotations

import ast
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
LIMIT = 150


def long_functions(root: pathlib.Path = _ROOT) -> list[tuple[int, str, int, str]]:
    """``(length, relative path, line, qualified name)``, longest first."""
    found = []
    for path in sorted((root / "weebot").rglob("*.py")):
        if "GitNexus-main" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(root).as_posix()

        def visit(node: ast.AST, prefix: str) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    length = child.end_lineno - child.lineno + 1
                    name = f"{prefix}{child.name}"
                    if length > LIMIT:
                        found.append((length, rel, child.lineno, name))
                    visit(child, name + ".")
                elif isinstance(child, ast.ClassDef):
                    visit(child, f"{prefix}{child.name}.")
                else:
                    visit(child, prefix)

        visit(tree, "")
    return sorted(found, reverse=True)


def main(argv: list[str]) -> int:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from quality_ceilings import check

    found = long_functions()
    if "--list" in argv:
        for length, rel, line, name in found:
            print(f"{length:5d}  {rel}:{line}  {name}")
    code, message = check("functions_over_150_lines", len(found))
    print(message, file=sys.stderr if code else sys.stdout)
    if code:
        print(
            "Split the function (ADR-007 seams) rather than raising the ceiling; if one was\n"
            "split, lower `functions_over_150_lines` in tasks/quality/ceilings.toml.",
            file=sys.stderr,
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
