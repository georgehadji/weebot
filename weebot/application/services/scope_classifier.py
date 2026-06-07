"""ScopeClassifier — detects task scope before entering full PlanActFlow.

Hallmark-inspired: before entering the heavy design flow, check if this is
a component-scope request that can skip macrosctructure, nav, footer, etc.
Similarly, weebot classifies tasks as SIMPLE (skip planner), COMPOUND
(skip verification), or COMPLEX (full PlanActFlow with CoVe).
"""
from __future__ import annotations

import re
from enum import Enum


class TaskScope(str, Enum):
    """Task scope classification for flow routing."""
    SIMPLE = "simple"        # One action — skip planner, execute directly
    COMPOUND = "compound"    # 2-5 actions — run planner, skip verification
    COMPLEX = "complex"      # Multi-step — full PlanActFlow with CoVe


# Patterns that indicate a single-action task (no planning needed)
_SIMPLE_PATTERNS: list[re.Pattern] = [
    re.compile(r"^(read|show|display|cat|list|ls|dir|get|fetch|view|open)\b", re.I),
    re.compile(r"^(run|execute|test|check|verify)\s+\w+", re.I),
    re.compile(r"^(what|who|when|where|how|why)\b", re.I),  # Factual questions
    re.compile(r"^(tell|explain|describe|define)\b", re.I),
]

# Patterns that indicate a compound task (light planning, skip CoVe)
_COMPOUND_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(move|copy|rename|organize|sort|tidy|clean)\b", re.I),
    re.compile(r"\b(create|make)\s+(a|the|some)\b", re.I),
    re.compile(r"\b(convert|transform|translate)\b", re.I),
    re.compile(r"\b(download|install|setup|configure)\b", re.I),
]

# Simple tasks are brief
_SIMPLE_MAX_WORDS: int = 15
_COMPOUND_MAX_WORDS: int = 40


class ScopeClassifier:
    """Classifies a user prompt into TaskScope for flow routing.

    Only classifies SIMPLE tasks when both a keyword pattern matches AND
    the prompt is short enough. This prevents false-positives on long
    research questions that happen to start with "what".

    Usage:
        classifier = ScopeClassifier()
        scope = classifier.classify("read the README file")
        # → TaskScope.SIMPLE
    """

    def classify(self, prompt: str) -> TaskScope:
        """Classify *prompt* into SIMPLE, COMPOUND, or COMPLEX."""
        words = len(prompt.split())

        # ── SIMPLE check ────────────────────────────────────────────
        # Must be short AND match a simple pattern
        if words <= _SIMPLE_MAX_WORDS:
            for pat in _SIMPLE_PATTERNS:
                if pat.search(prompt):
                    return TaskScope.SIMPLE

        # ── COMPOUND check ──────────────────────────────────────────
        if words <= _COMPOUND_MAX_WORDS:
            for pat in _COMPOUND_PATTERNS:
                if pat.search(prompt):
                    return TaskScope.COMPOUND

        # ── Default: COMPLEX ────────────────────────────────────────
        return TaskScope.COMPLEX
