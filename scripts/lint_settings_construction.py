#!/usr/bin/env python3
"""AST ratchet on direct ``WeebotSettings(...)`` construction in production code.

ICM fix plan W2.2 (finding F16, tasks/icm_fix_plan.md). Every
``WeebotSettings()`` re-reads ``.env`` and re-validates every field; one ran
per inbound gateway message. Production code reads the process-wide instance
from ``weebot.config.settings.get_settings()`` (or ``Container.get(WeebotSettings)``)
instead. This counts the calls that remain, so the number can only go down.

A call is any ``WeebotSettings(...)`` or ``<module>.WeebotSettings(...)``.
``weebot/config/settings.py`` is excluded: ``get_settings()`` itself must
construct one. Tests are excluded: they build instances with explicit kwargs
on purpose.

Enforced as a **bidirectional** ratchet, like the others: exit 0 only when
count == the ``settings_construction`` ceiling in tasks/quality/ceilings.toml.
Lower the ceiling in the same commit that migrates a site.

Usage:
    python scripts/lint_settings_construction.py [paths ...]
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

# The accessor's own module.
EXEMPT_FILES = {Path("weebot/config/settings.py")}


def _is_settings_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "WeebotSettings"
    return isinstance(func, ast.Attribute) and func.attr == "WeebotSettings"


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
            if SKIP_PARTS & set(path.parts) or path in EXEMPT_FILES:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError) as exc:
                print(f"{path}: could not parse ({exc})", file=sys.stderr)
                continue
            hits.extend(f"{path}:{n.lineno}" for n in ast.walk(tree) if _is_settings_call(n))
    return hits


def _ceiling_check(actual: int) -> tuple[int, str]:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from quality_ceilings import check

    return check("settings_construction", actual)


def main(argv: list[str]) -> int:
    paths = tuple(argv[1:]) or DEFAULT_PATHS
    hits = find_violations(paths)
    for hit in hits:
        print(f"{hit}: WeebotSettings() built directly; use get_settings()")
    code, message = _ceiling_check(len(hits))
    print(f"\n{message}")
    if code:
        print(
            "Read settings with weebot.config.settings.get_settings() "
            "or Container.get(WeebotSettings).",
            file=sys.stderr,
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
