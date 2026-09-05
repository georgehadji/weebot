#!/usr/bin/env python3
"""AST-based linter for blocking I/O in async functions.

Detects patterns like open(), .read_text(), sqlite3.connect(),
time.sleep(), and subprocess.run() inside async def functions
that are NOT wrapped in asyncio.to_thread() or loop.run_in_executor().

Exit code: 0 if clean, 1 if violations found.

Usage:
    python scripts/lint_async_io.py [paths ...]
"""
from __future__ import annotations

import ast
import re
import pathlib
import sys
from pathlib import Path


# The ceiling lives in tasks/quality/ceilings.toml (phase B2), enforced in both
# directions. Before the scope/dedupe fixes this script reported 83 for these same 29 sites:
# it descended into nested sync helpers (the correct `asyncio.to_thread` pattern
# in the persistence stores), matched `aiofiles.open(` as blocking, and emitted
# one report per Call node rather than per line.

BLOCKING_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bopen\s*\("),
    re.compile(r"\.read_text\s*\("),
    re.compile(r"\.read_bytes\s*\("),
    re.compile(r"\.write_text\s*\("),
    re.compile(r"sqlite3\.connect\s*\("),
    re.compile(r"subprocess\.run\s*\("),
    re.compile(r"subprocess\.Popen\s*\("),
    re.compile(r"subprocess\.call\s*\("),
    re.compile(r"time\.sleep\s*\("),
]

SKIP_PATHS: set[str] = {
    ".venv", "Output", "node_modules", "__pycache__",
    "scripts", "examples", "weebot/GitNexus-main",
}


# Async-native wrappers whose names collide with the blocking patterns below.
# `\bopen\s*\(` matches after a dot, so `aiofiles.open(...)` — which is correct
# async code — was reported as blocking.
ASYNC_SAFE_PREFIXES: tuple[str, ...] = ("aiofiles.", "anyio.", "await aiofiles", "await anyio")


def _own_body(node: ast.AST):
    """Yield descendants of *node* without entering nested function scopes.

    ``ast.walk`` descends into nested ``def``s, which both misattributed calls
    in a sync helper to the enclosing ``async def`` and reported calls in a
    nested ``async def`` once per enclosing function.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield child
        yield from _own_body(child)


def _check_file(path: Path) -> list[str]:
    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    if "async def" not in source:
        return []

    violations: list[str] = []
    # One report per source line. A single line can hold several Call nodes
    # (`json.loads(p.read_text())` is two), and each used to emit its own
    # violation, inflating the total without naming a new site.
    reported_lines: set[int] = set()

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue

        for child in _own_body(node):
            if not isinstance(child, ast.Call):
                continue

            call_line = getattr(child, "lineno", 0)
            source_lines = source.splitlines()
            if call_line <= 0 or call_line > len(source_lines):
                continue

            line_text = source_lines[call_line - 1].strip()

            if "asyncio.to_thread" in line_text or "run_in_executor" in line_text:
                continue

            if any(prefix in line_text for prefix in ASYNC_SAFE_PREFIXES):
                continue

            context_start = max(0, call_line - 3)
            context_end = min(len(source_lines), call_line + 1)
            context = "\n".join(source_lines[context_start:context_end])
            if "asyncio.to_thread" in context or "run_in_executor" in context:
                continue

            if call_line in reported_lines:
                continue

            for pattern in BLOCKING_PATTERNS:
                if pattern.search(line_text):
                    reported_lines.add(call_line)
                    violations.append(
                        f"{path}:{call_line}: "
                        f"Blocking call in async function '{node.name}': {line_text[:100]}"
                    )
                    break

    return violations


# The ceiling lives in tasks/quality/ceilings.toml, and the rule that compares
# against it lives in scripts/quality_ceilings.py. Both are shared by all five
# ratchets so that the rule cannot drift between them -- and so that lowering a
# ceiling is a diff in one declarative file rather than an edit buried here.
def _ceiling_check(actual: int) -> tuple[int, str]:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from quality_ceilings import check

    return check("blocking_io_in_async", actual)


def main() -> int:
    paths = sys.argv[1:] if len(sys.argv) > 1 else ["weebot", "cli"]
    all_violations: list[str] = []
    seen: set[str] = set()

    for arg in paths:
        root = Path(arg)
        if not root.exists():
            continue

        if root.is_file():
            files = [root]
        else:
            files = sorted(root.rglob("*.py"))

        for file_path in files:
            rel = file_path.as_posix()
            if SKIP_PATHS & set(file_path.parts):
                continue
            if file_path.name.startswith("test_"):
                continue

            key = str(file_path)
            if key in seen:
                continue
            seen.add(key)

            violations = _check_file(file_path)
            all_violations.extend(violations)

    if all_violations:
        print("=== Blocking I/O in async functions ===")
        for v in sorted(all_violations):
            print(v)
        code, message = _ceiling_check(len(all_violations))
        print(f"\n{message}")
        print("Wrap blocking calls with 'await asyncio.to_thread(...)' or 'loop.run_in_executor(...)'.")
        return code

    print("No blocking I/O violations found in async functions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
