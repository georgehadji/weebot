"""Static Ponytail quality hints for CodeReviewerService.

These are lightweight, rule-based heuristics that run only when Ponytail mode
is active. They produce *hints*, not hard failures — the LLM reviewer has the
final say.
"""

from __future__ import annotations

import re

_DEFINITION = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s", re.MULTILINE)
# Indented, so it sits inside a body rather than at module level.
_CONTROL_FLOW = re.compile(r"^\s+(?:if|elif|for|while|try|match)\b", re.MULTILINE)
# `\bassert` also covers self.assertEqual and friends.
_HAS_CHECK = re.compile(r"\bassert|__main__|\bunittest\b|\bpytest\b|\bdef test_")
# Statements only, not words in prose: `global` and `while True:` at line
# start, and a lock constructor (Lock(, RLock(, asyncio.Lock() -- never
# `block` or `clock`, which are lowercase.
_SHORTCUT = re.compile(r"^\s*global\s+\w|^\s*while True:|\b\w*Lock\(", re.MULTILINE)


def static_ponytail_review(code: str) -> list[str]:
    """Return Ponytail-style findings for *code*.

    Args:
        code: Code snippet or step result to inspect.

    Returns:
        List of finding strings (may be empty).
    """
    findings: list[str] = []
    if not code:
        return findings

    # Interface / abstract base with one implementation
    if re.search(r"class \w+\(.*ABC.*\):", code) and code.count("class ") == 2:
        findings.append("yagni: abstract base with a single implementation")

    # Manual loop building a dict where dict(zip(...)) would work
    if re.search(r"for .* in .*:\n\s+\w+\[.*\] =", code):
        findings.append("shrink: consider dict(zip(keys, values))")

    # Imports that duplicate stdlib (examples)
    if "import retrying" in code:
        findings.append("stdlib: use tenacity or functools.wraps retry instead of retrying")

    # Non-trivial = a def/class with branching or looping in its body; a
    # one-line function needs no test.
    if (
        _DEFINITION.search(code)
        and _CONTROL_FLOW.search(code)
        and not _HAS_CHECK.search(code)
    ):
        findings.append(
            "test: non-trivial logic needs a runnable check "
            "(assert-based self-check or __main__ demo)"
        )

    # Check for shortcuts lacking a "ponytail:" comment explaining the ceiling
    if _SHORTCUT.search(code) and "ponytail:" not in code:
        findings.append(
            "ponytail-comment: mark deliberate simplifications with a ponytail: "
            "comment detailing the ceiling and upgrade path"
        )

    return findings
