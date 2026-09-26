"""Static Ponytail quality hints for CodeReviewerService.

These are lightweight, rule-based heuristics that run only when Ponytail mode
is active. They produce *hints*, not hard failures — the LLM reviewer has the
final say.
"""

from __future__ import annotations

import re


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

    # Check for missing tests on non-trivial code (classes/functions without checks)
    if ("def " in code or "class " in code) and not any(
        kw in code for kw in ("assert", "__main__", "unittest", "pytest", "test_", "self.assert")
    ):
        findings.append(
            "test: non-trivial logic needs a runnable check (assert-based self-check or __main__ demo)"
        )

    # Check for shortcuts lacking a "ponytail:" comment explaining the ceiling
    if any(pattern in code for pattern in ("global ", "while True:", "lock")) and "ponytail:" not in code:
        findings.append(
            "ponytail-comment: mark deliberate simplifications with a ponytail: comment detailing the ceiling and upgrade path"
        )

    return findings
