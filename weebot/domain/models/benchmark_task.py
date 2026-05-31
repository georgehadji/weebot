"""Benchmark task domain models — pure data, no weebot imports.

Defines WeebotTask and SamplePair for the SIA-compatible benchmark harness.
Tasks are loaded from directories (task.md + samples.json) and run through
PlanActFlow via BenchmarkRunner in the application layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


@dataclass(frozen=True)
class SamplePair:
    """One (prompt, expected_answer) pair within a benchmark task."""
    prompt: str
    expected_answer: Optional[str] = None


@dataclass(frozen=True)
class WeebotTask:
    """A benchmark task definition following SIA's task protocol.

    A task directory contains:
      task.md         — human-readable description (becomes WeebotTask.description)
      samples.json    — list of {"prompt": "...", "expected_answer": "..."} objects
      evaluate.py     — optional custom scorer: evaluate(session, expected) -> float
    """
    task_id: str
    description: str
    samples: tuple[SamplePair, ...]  # frozen tuple for hashability
    pass_threshold: float = 0.5
    tags: tuple[str, ...] = field(default_factory=tuple)
    custom_scorer: Optional[Callable] = None   # async fn(session, expected_answer) -> float
    source_dir: Optional[Path] = None
