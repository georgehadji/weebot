"""Concrete termination conditions."""
from __future__ import annotations

from weebot.application.termination.base import (
    TerminationCondition,
    TerminationContext,
    TerminationResult,
)


class MaxIterationTermination(TerminationCondition):
    """Terminate after a maximum number of iterations."""

    def __init__(self, max_iterations: int) -> None:
        if max_iterations < 1:
            raise ValueError(f"max_iterations must be >= 1, got {max_iterations}")
        self._max = max_iterations

    def check(self, ctx: TerminationContext) -> TerminationResult:
        if ctx.iteration >= self._max:
            return TerminationResult(
                True, f"max iterations ({self._max}) reached",
            )
        return TerminationResult(False)


class TokenBudgetTermination(TerminationCondition):
    """Terminate when cumulative token usage exceeds a budget.

    Args:
        max_tokens: Maximum total tokens (prompt + completion) before stopping.
    """

    def __init__(self, max_tokens: int) -> None:
        if max_tokens < 1:
            raise ValueError(f"max_tokens must be >= 1, got {max_tokens}")
        self._max = max_tokens

    def check(self, ctx: TerminationContext) -> TerminationResult:
        if ctx.total_tokens >= self._max:
            return TerminationResult(
                True,
                f"token budget ({self._max:,}) exhausted "
                f"(used {ctx.total_tokens:,})",
            )
        return TerminationResult(False)


class WallClockTermination(TerminationCondition):
    """Terminate after a maximum wall-clock duration.

    Args:
        max_seconds: Maximum seconds of wall time before stopping.
    """

    def __init__(self, max_seconds: float) -> None:
        if max_seconds <= 0:
            raise ValueError(
                f"max_seconds must be > 0, got {max_seconds}"
            )
        self._max = max_seconds

    def check(self, ctx: TerminationContext) -> TerminationResult:
        if ctx.elapsed_seconds >= self._max:
            return TerminationResult(
                True,
                f"wall clock timeout ({self._max:.0f}s) exceeded"
                f" (elapsed {ctx.elapsed_seconds:.0f}s)",
            )
        return TerminationResult(False)


class TextMentionTermination(TerminationCondition):
    """Terminate when specific text is found in recent messages.

    Args:
        text: Case-insensitive substring to search for.
        scan_last_n: Number of most recent messages to scan.
    """

    def __init__(self, text: str, scan_last_n: int = 5) -> None:
        if scan_last_n < 1:
            raise ValueError(
                f"scan_last_n must be >= 1, got {scan_last_n}"
            )
        self._text = text.lower()
        self._scan_last_n = scan_last_n

    def check(self, ctx: TerminationContext) -> TerminationResult:
        if ctx.last_messages:
            for msg in ctx.last_messages[-self._scan_last_n:]:
                content = str(msg.get("content", "")).lower()
                if self._text in content:
                    return TerminationResult(
                        True,
                        f"text '{self._text}' mentioned in output",
                    )
        return TerminationResult(False)
