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
import sys
from pathlib import Path


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


def _check_file(path: Path) -> list[str]:
    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    if "async def" not in source:
        return []

    violations: list[str] = []

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue

        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue

            call_line = getattr(child, "lineno", 0)
            source_lines = source.splitlines()
            if call_line <= 0 or call_line > len(source_lines):
                continue

            line_text = source_lines[call_line - 1].strip()

            if "asyncio.to_thread" in line_text or "run_in_executor" in line_text:
                continue

            context_start = max(0, call_line - 3)
            context_end = min(len(source_lines), call_line + 1)
            context = "\n".join(source_lines[context_start:context_end])
            if "asyncio.to_thread" in context or "run_in_executor" in context:
                continue

            for pattern in BLOCKING_PATTERNS:
                if pattern.search(line_text):
                    violations.append(
                        f"{path}:{call_line}: "
                        f"Blocking call in async function '{node.name}': {line_text[:100]}"
                    )
                    break

    return violations


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
            if any(skip in rel for skip in SKIP_PATHS):
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
        print(f"\n{len(all_violations)} violation(s) found.")
        print("Wrap blocking calls with 'await asyncio.to_thread(...)' or 'loop.run_in_executor(...)'.")
        return 1

    print("No blocking I/O violations found in async functions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
