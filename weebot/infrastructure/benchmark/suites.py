"""Benchmark suites — versioned prompt sets per capability axis.

Each suite is a collection of items that probe a specific capability.
Results are scored deterministically (exact/case-insensitive match) to
produce a 0..10 score without requiring an evaluator model.

Suites are designed to be fast and cheap (≤10 items each, short prompts).
"""

from __future__ import annotations

import re

# ── Shared pattern helpers ─────────────────────────────────────────


def _has_all(text: str, *keywords: str) -> bool:
    """Return True if all *keywords appear in *text* (case-insensitive)."""
    lower = text.lower()
    return all(kw.lower() in lower for kw in keywords)


def _count_matches(text: str, *patterns: str) -> int:
    """Count how many *patterns* appear in *text* (pre-compiled or string)."""
    lower = text.lower()
    total = 0
    for p in patterns:
        if isinstance(p, re.Pattern):
            if p.search(text):
                total += 1
        else:
            if p.lower() in lower:
                total += 1
    return total


# ── Suite type ──────────────────────────────────────────────────────


class BenchmarkItem:
    """A single benchmark probe.

    Args:
        prompt: The prompt/query to send to the model.
        expected: Keywords or patterns expected in a correct response.
        rubric_score: Score (0..10) assigned when *all* expected keywords
            are present.  Defaults to 10 (full credit).
    """

    def __init__(self, prompt: str, expected: list[str], rubric_score: float = 10.0) -> None:
        self.prompt = prompt
        self.expected = expected
        self.rubric_score = rubric_score

    def score_response(self, response: str) -> float:
        """Score *response* against the expected patterns.

        Uses case-insensitive substring matching.  Returns *rubric_score*
        when all expected substrings are present, 0.0 otherwise.
        This is intentionally strict — partial matches are scored 0 to
        avoid rewarding models that produce plausible but wrong answers.
        """
        lower = response.lower()
        if all(kw.lower() in lower for kw in self.expected):
            return self.rubric_score
        return 0.0


class BenchmarkSuite:
    """A collection of items probing a single capability axis.

    Args:
        name: Human-readable name (e.g. "Python coding").
        axis: The capability axis this suite measures.
        items: List of ``BenchmarkItem`` instances.
        version: Suite version string for cache-busting.
    """

    def __init__(
        self, name: str, axis: str, items: list[BenchmarkItem], version: str = "1.0"
    ) -> None:
        self.name = name
        self.axis = axis
        self.items = items
        self.version = version

    def score_all(self, responses: list[str]) -> float:
        """Score all responses and return a normalised 0..10 score.

        Args:
            responses: One response per item (same order as ``self.items``).
        """
        if not self.items:
            return 0.0
        total = 0.0
        max_score = 0.0
        for item, resp in zip(self.items, responses):
            s = item.score_response(resp)
            total += s
            max_score += item.rubric_score
        if max_score == 0.0:
            return 0.0
        return (total / max_score) * 10.0


# ── Suite definitions ───────────────────────────────────────────────

REASONING_SUITE = BenchmarkSuite(
    name="Logical reasoning (3 items)",
    axis="reasoning",
    version="1.0",
    items=[
        BenchmarkItem(
            "If all humans are mortal and Socrates is human, "
            "what can we conclude about Socrates?",
            expected=["Socrates", "mortal"],
        ),
        BenchmarkItem(
            "A bat and a ball cost $1.10 in total. "
            "The bat costs $1.00 more than the ball. "
            "How much does the ball cost?",
            expected=["5", "cent", "0.05", "5¢"],
        ),
        BenchmarkItem(
            "You have a 3-gallon jug and a 5-gallon jug. " "How can you measure exactly 4 gallons?",
            expected=["3", "5", "fill", "pour"],
        ),
    ],
)

CODING_SUITE = BenchmarkSuite(
    name="Python coding (3 items)",
    axis="coding",
    version="1.0",
    items=[
        BenchmarkItem(
            "Write a Python function to reverse a linked list in place. " "Return the new head.",
            expected=["def", "reverse", "next", "prev", "head"],
        ),
        BenchmarkItem(
            "Write a Python one-liner using list comprehension "
            "to get squares of even numbers from [1..10].",
            expected=["x**2", "for", "if", "x % 2", "==", "0"],
        ),
        BenchmarkItem(
            "What is the time complexity of quicksort in the worst case?",
            expected=["O(n²)", "O(n^2)", "quadratic", "O(n**2)"],
        ),
    ],
)

WRITING_SUITE = BenchmarkSuite(
    name="Clarity & grammar (2 items)",
    axis="writing",
    version="1.0",
    items=[
        BenchmarkItem(
            'Fix the grammar: "He go to school yesterday."', expected=["went", "to school"]
        ),
        BenchmarkItem(
            "Write one short sentence that means the same as: "
            '"The meeting was postponed due to the fact that '
            'the manager was not available."',
            expected=["postponed", "manager", "not available"],
        ),
    ],
)

MATH_SUITE = BenchmarkSuite(
    name="Basic arithmetic (3 items)",
    axis="math",
    version="1.0",
    items=[
        BenchmarkItem("What is 15 × 37?", expected=["555"]),
        BenchmarkItem("Solve for x: 3x + 7 = 22", expected=["5", "x = 5"]),
        BenchmarkItem(
            "What is the probability of rolling a sum of 7 " "with two fair six-sided dice?",
            expected=["1/6", "1 in 6", "16.67%", "0.1667", "16.7%"],
        ),
    ],
)

LONG_CONTEXT_SUITE = BenchmarkSuite(
    name="Long context recall (2 items)",
    axis="long_context",
    version="1.0",
    items=[
        BenchmarkItem(
            "Summarise the following text in one sentence: "
            '"The quick brown fox jumps over the lazy dog. '
            "It was a sunny day in the forest, and all the animals "
            "were out enjoying the weather. The fox, being quick and "
            'brown, easily cleared the fence and continued his journey."',
            expected=["fox", "jump", "dog"],
        ),
        BenchmarkItem("From the text above, what colour was the fox?", expected=["brown"]),
    ],
)

TOOL_USE_SUITE = BenchmarkSuite(
    name="Tool use reasoning (2 items)",
    axis="tool_use",
    version="1.0",
    items=[
        BenchmarkItem(
            "You have a web_search tool. " "How would you find the current population of Tokyo?",
            expected=["web_search", "Tokyo", "population"],
        ),
        BenchmarkItem(
            "If a file read returns 'File not found', what tool "
            "would you use next to investigate?",
            expected=["list", "ls", "find", "glob"],
        ),
    ],
)

# ── Registry ────────────────────────────────────────────────────────

ALL_SUITES: list[BenchmarkSuite] = [
    REASONING_SUITE,
    CODING_SUITE,
    WRITING_SUITE,
    MATH_SUITE,
    LONG_CONTEXT_SUITE,
    TOOL_USE_SUITE,
]

SUITES_BY_AXIS: dict[str, BenchmarkSuite] = {s.axis: s for s in ALL_SUITES}
