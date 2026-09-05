#!/usr/bin/env python3
"""AST-based linter for exception handlers whose entire body is ``pass``.

Replaces a Makefile grep that could only match the single-line form
``except X: pass``. The ordinary two-line form ::

    except Exception:
        pass

never matched it, so the gate reported clean while 139 such handlers existed.
A swallowed exception is invisible at runtime; the project policy is that every
handler logs at least at DEBUG level.

Enforced as a ratchet: the run fails only when the count *exceeds* CEILING, so
existing debt does not block the build but no new site can be added. Lower
CEILING as sites are fixed; it must never be raised.

Exit code: 0 if count <= CEILING, 1 otherwise.

Usage:
    python scripts/lint_except_pass.py [paths ...]
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Current known count. Lower this as handlers are fixed; never raise it.
CEILING = 139

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


def main(argv: list[str]) -> int:
    paths = tuple(argv[1:]) or DEFAULT_PATHS
    hits = find_violations(paths)
    for hit in hits:
        print(f"{hit}: exception handler body is only `pass` — log at DEBUG instead")
    print(f"\n{len(hits)} silent handler(s) found; ceiling is {CEILING}.")
    if len(hits) > CEILING:
        print(
            f"ERROR: {len(hits) - CEILING} new silent handler(s). "
            "Log the exception at DEBUG rather than swallowing it.",
            file=sys.stderr,
        )
        return 1
    if len(hits) < CEILING:
        print(f"Ceiling can be lowered to {len(hits)} in scripts/lint_except_pass.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
