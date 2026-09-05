#!/usr/bin/env python3
"""AST-based linter for exception handlers whose entire body is ``pass``.

Replaces a Makefile grep that could only match the single-line form
``except X: pass``. The ordinary two-line form ::

    except Exception:
        pass

never matched it, so the gate reported clean while 139 such handlers existed.
A swallowed exception is invisible at runtime; the project policy is that every
handler logs at least at DEBUG level.

Enforced as a **bidirectional** ratchet (phase B2): the run fails when the count
exceeds the ceiling in ``tasks/quality/ceilings.toml`` *and* when it falls below
it. The second half is the point -- a ceiling that only blocks upward movement
sits where it was first measured forever, and the slack between actual and
ceiling is exactly where a regression hides unnoticed. Lower the ceiling in the
same commit that removes the debt; it may never be raised.

Exit code: 0 only when count == ceiling.

Usage:
    python scripts/lint_except_pass.py [paths ...]
"""

from __future__ import annotations

import ast
import pathlib
import sys
from pathlib import Path

# Current known count. Lower this as handlers are fixed; never raise it.

DEFAULT_PATHS = ("weebot", "cli")

# Vendored or non-runtime trees. Mirrors the ruff/bandit exclusions so the
# three tools report over the same surface.
SKIP_PARTS = {
    ".venv",
    "Output",
    "node_modules",
    "__pycache__",
    "GitNexus-main",
    "tests",
}


def _is_silent(handler: ast.ExceptHandler) -> bool:
    """True when the handler body is exactly ``pass`` (or ``...``)."""
    if len(handler.body) != 1:
        return False
    node = handler.body[0]
    if isinstance(node, ast.Pass):
        return True
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and node.value.value is Ellipsis
    )


def find_violations(paths: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for root in paths:
        for path in sorted(Path(root).rglob("*.py")):
            if SKIP_PARTS & set(path.parts):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError) as exc:
                print(f"{path}: could not parse ({exc})", file=sys.stderr)
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and _is_silent(node):
                    hits.append(f"{path}:{node.lineno}")
    return hits


# The ceiling lives in tasks/quality/ceilings.toml, and the rule that compares
# against it lives in scripts/quality_ceilings.py. Both are shared by all five
# ratchets so that the rule cannot drift between them -- and so that lowering a
# ceiling is a diff in one declarative file rather than an edit buried here.
def _ceiling_check(actual: int) -> tuple[int, str]:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from quality_ceilings import check

    return check("silent_except_handlers", actual)


def main(argv: list[str]) -> int:
    paths = tuple(argv[1:]) or DEFAULT_PATHS
    hits = find_violations(paths)
    for hit in hits:
        print(f"{hit}: exception handler body is only `pass` — log at DEBUG instead")
    code, message = _ceiling_check(len(hits))
    print(f"\n{message}")
    if code:
        print(
            "Log the exception at DEBUG rather than swallowing it.",
            file=sys.stderr,
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
