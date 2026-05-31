"""Scoring adapters for the ScoringPort interface.

Provides three scoring strategies matching the SkillOpt paper:
- ExactMatchScorer: normalized string comparison for QA benchmarks
- ExecutionResultScorer: output artifact comparison for code/spreadsheets
- VerifierScorer: LLM-based verification with 0.0–1.0 confidence scores
"""
from __future__ import annotations

from .exact_match_scorer import ExactMatchScorer
from .execution_scorer import ExecutionResultScorer
from .verifier_scorer import VerifierScorer

__all__ = [
    "ExactMatchScorer",
    "ExecutionResultScorer",
    "VerifierScorer",
]
