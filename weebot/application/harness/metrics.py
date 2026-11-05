"""What one benchmark run cost and how it went (plan §13, the numbers eval-gated items attach).

Pass rate alone cannot tell whether a change made the agent cheaper or its edits more reliable.
Three counters fill that in:

* ``UsageTally`` folds ``LLMCallCompleted`` domain events into per-session calls, tokens and USD.
  Subscribe ``tally.on_domain_event`` to the bus once, before the run.
* ``count_tool_events`` reads the events a flow yields: tool calls, tool errors and
  *edit-failure loops* (two or more failed ``file_editor`` calls in a row on one file).
* ``RunMetrics`` carries both into ``BenchmarkResult``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

EDIT_TOOL = "file_editor"


@dataclass(frozen=True)
class RunMetrics:
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    tool_calls: int = 0
    tool_errors: int = 0
    edit_failure_loops: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UsageTally:
    """Per-session LLM usage, fed by ``LLMCallCompleted`` events."""

    def __init__(self) -> None:
        self._usage: dict[str, list[float]] = {}

    async def on_domain_event(self, event: Any) -> None:
        if getattr(event, "type", "") != "llm_call_completed":
            return
        row = self._usage.setdefault(getattr(event, "session_id", "") or "", [0, 0, 0, 0.0])
        row[0] += 1
        row[1] += int(getattr(event, "prompt_tokens", 0) or 0)
        row[2] += int(getattr(event, "completion_tokens", 0) or 0)
        row[3] += float(getattr(event, "cost", 0.0) or 0.0)

    def of(self, session_id: str) -> tuple[int, int, int, float]:
        calls, prompt, completion, cost = self._usage.get(session_id, [0, 0, 0, 0.0])
        return int(calls), int(prompt), int(completion), float(cost)


def count_tool_events(events: list[Any]) -> tuple[int, int, int]:
    """``(tool_calls, tool_errors, edit_failure_loops)`` from the events a flow yielded.

    A loop is counted once, when a file's run of failed edits reaches two; a success on that
    file, or a failure on another file, ends the run.
    """
    calls = errors = loops = 0
    streak_path: str | None = None
    streak = 0
    for event in events:
        if getattr(event, "type", "") != "tool" or getattr(event, "status", None) != "called":
            continue
        calls += 1
        failed = bool(getattr(event, "is_error", False))
        errors += failed
        if getattr(event, "tool_name", "") != EDIT_TOOL:
            continue
        path = str((getattr(event, "function_args", None) or {}).get("path", ""))
        if not failed:
            streak_path, streak = None, 0
            continue
        streak = streak + 1 if path == streak_path else 1
        streak_path = path
        loops += streak == 2
    return calls, errors, loops
