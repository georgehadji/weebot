#!/usr/bin/env python3
"""AST ratchet on hand-built ``Container()`` outside ``weebot/application/di``.

ICM fix plan W5.3 (finding F28, tasks/icm_fix_plan.md). Every ``Container()``
followed by ``configure_defaults()`` builds a second object graph with its own
event bus, state repository and LLM adapters. Code that does this mid-run sees
none of the process's real singletons: a flow built that way publishes to a
bus nobody subscribed to. Composition roots (web lifespan, CLI entry points)
build one container and pass collaborators in; everything else should take
them as arguments. This counts the sites that remain, so the number can only
go down.

A call is any ``Container(...)``, ``<module>.Container(...)`` or
``import_module(...).Container(...)``. ``weebot/application/di/`` is excluded:
it defines the container. Tests and ``scripts/`` are excluded.

Enforced as a **bidirectional** ratchet, like the others: exit 0 only when
count == the ``container_construction`` ceiling in tasks/quality/ceilings.toml.
Lower the ceiling in the same commit that migrates a site.

Usage:
    python scripts/lint_container_construction.py [paths ...]
"""

from __future__ import annotations

import ast
import pathlib
import sys
from pathlib import Path

DEFAULT_PATHS = ("weebot", "cli", "run.py", "run_mcp.py")

SKIP_PARTS = {
    ".venv",
    "Output",
    "node_modules",
    "__pycache__",
    "GitNexus-main",
    "tests",
}

# The container's own package.
EXEMPT_DIR = Path("weebot/application/di")


def _is_container_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "Container"
    return isinstance(func, ast.Attribute) and func.attr == "Container"


def _files(root: str):
    path = Path(root)
    if path.is_file():
        yield path
        return
    yield from sorted(path.rglob("*.py"))


def find_violations(paths: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for root in paths:
        for path in _files(root):
            if SKIP_PARTS & set(path.parts) or path.is_relative_to(EXEMPT_DIR):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError) as exc:
                print(f"{path}: could not parse ({exc})", file=sys.stderr)
                continue
            hits.extend(f"{path}:{n.lineno}" for n in ast.walk(tree) if _is_container_call(n))
    return sorted(hits, key=lambda h: (h.rsplit(":", 1)[0], int(h.rsplit(":", 1)[1])))


def _ceiling_check(actual: int) -> tuple[int, str]:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from quality_ceilings import check

    return check("container_construction", actual)


def main(argv: list[str]) -> int:
    paths = tuple(argv[1:]) or DEFAULT_PATHS
    hits = find_violations(paths)
    for hit in hits:
        print(f"{hit}: Container() built by hand; take collaborators as arguments")
    code, message = _ceiling_check(len(hits))
    print(f"\n{message}")
    if code:
        print(
            "Resolve from the one container the entry point built (app.state.container, "
            "or a parameter) instead of building another.",
            file=sys.stderr,
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
