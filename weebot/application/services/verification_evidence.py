"""Verification evidence (H20b): did the checks run after the last edit?

``classify_verification_command`` is a table lookup over a shell command. The executor uses it to
append two kinds of ``session_flag`` row to the effect ledger: ``code_written`` for a source edit
and ``verification_ran`` for a test, build or lint command, with whether it passed.
``evidence_status`` reads those rows back in order.

shortcut: only ``bash`` / ``powershell`` commands are classified, not a test run launched from
inside ``python_execute``; add a classifier for that code if a session needs it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Literal

CODE_WRITTEN = "code_written"
VERIFICATION_RAN = "verification_ran"

EvidenceStatus = Literal["verified", "stale_after_edit"]

SOURCE_SUFFIXES = frozenset(
    {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".rs", ".go", ".cs", ".java", ".kt", ".c", ".cc",
     ".cpp", ".h", ".hpp", ".rb", ".php", ".swift"}
)

# A segment starts with the program, optionally behind a runner such as ``uv run`` or ``python -m``,
# so ``echo pytest`` and ``pip install pytest-cov`` are not verification.
_RUNNER = r"^(?:(?:uv|poetry|pipenv)\s+run\s+|npx\s+|python[\d.]*\s+-m\s+|py\s+-m\s+)?(?:\S*[/\\])?"
# (kind, pattern over one shell segment). The first match wins.
_TABLE: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(_RUNNER + pattern))
    for kind, pattern in (
        ("pytest", r"pytest\b"),
        ("npm_test", r"(?:npm|pnpm|yarn)\s+(?:run\s+)?test\b"),
        ("npm_build", r"(?:npm|pnpm|yarn)\s+run\s+build\b"),
        ("make", r"make\s+(?:check|test)\b"),
        ("ruff", r"ruff\s+check\b"),
        ("tsc", r"tsc\b"),
        ("cargo_test", r"cargo\s+test\b"),
        ("go_test", r"go\s+test\b"),
        ("dotnet_test", r"dotnet\s+test\b"),
        ("mvn_test", r"mvn\s+(?:\S+\s+)*test\b"),
    )
)
_SEGMENTS = re.compile(r"&&|\|\||[;|\n]")


def classify_verification_command(command: str | Sequence[str]) -> str | None:
    """The verification kind of a shell command, or None when it is not one.

    A chain such as ``cd app && pytest -q`` classifies by its first matching segment.
    """
    text = command if isinstance(command, str) else " ".join(command)
    for segment in _SEGMENTS.split(text):
        for kind, pattern in _TABLE:
            if pattern.search(segment.strip()):
                return kind
    return None


def is_source_file(path: str) -> bool:
    return any(path.lower().endswith(suffix) for suffix in SOURCE_SUFFIXES)


def evidence_status(rows: Sequence[dict[str, Any]]) -> EvidenceStatus | None:
    """None when no source was edited; else whether a passing check followed the last edit.

    *rows* are the session's flag rows, oldest first. A failing run is never evidence.
    """
    last_edit = last_pass = -1
    for index, row in enumerate(rows):
        if row.get("kind") == CODE_WRITTEN:
            last_edit = index
        elif row.get("kind") == VERIFICATION_RAN and row.get("ok"):
            last_pass = index
    if last_edit < 0:
        return None
    return "verified" if last_pass > last_edit else "stale_after_edit"


def commands_run(rows: Sequence[dict[str, Any]]) -> list[str]:
    """The verification commands that ran, with their outcome, in order."""
    return [
        f"{row.get('command', row.get('verification', '?'))} "
        f"({'passed' if row.get('ok') else 'failed'})"
        for row in rows
        if row.get("kind") == VERIFICATION_RAN
    ]
