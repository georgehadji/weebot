"""Base classes + CompositeTermination for termination conditions."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TerminationContext:
    """Context passed to each termination condition check.

    Attributes:
        iteration: Current loop iteration count.
        total_tokens: Cumulative token usage.
        elapsed_seconds: Wall-clock time since flow started.
        last_messages: Last N message dicts from the conversation buffer.
    """
    iteration: int = 0
    total_tokens: int = 0
    elapsed_seconds: float = 0.0
    last_messages: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class TerminationResult:
    """Result of a termination condition check."""
    should_terminate: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.should_terminate


class TerminationCondition(ABC):
    """Abstract base for all termination conditions.

    Use ``|`` and ``&`` operators to compose conditions:
        condition1 | condition2  # stop if EITHER triggers
        condition1 & condition2  # stop only if BOTH trigger
    """

    @abstractmethod
    def check(self, ctx: TerminationContext) -> TerminationResult: ...

    def __or__(self, other: "TerminationCondition") -> "CompositeTermination":
        return CompositeTermination([self, other], mode="any")

    def __and__(self, other: "TerminationCondition") -> "CompositeTermination":
        return CompositeTermination([self, other], mode="all")


class CompositeTermination(TerminationCondition):
    """Combines multiple conditions with AND/OR logic.

    Args:
        conditions: List of termination conditions to compose.
        mode: ``"any"`` for OR (any condition triggers stop),
              ``"all"`` for AND (all conditions must trigger).
    """

    def __init__(
        self,
        conditions: list[TerminationCondition],
        mode: str = "any",
    ) -> None:
        if mode not in ("any", "all"):
            raise ValueError(f"mode must be 'any' or 'all', got {mode!r}")
        self._conditions = list(conditions)
        self._mode = mode

    def check(self, ctx: TerminationContext) -> TerminationResult:
        results = [c.check(ctx) for c in self._conditions]
        if self._mode == "any":
            for r in results:
                if r.should_terminate:
                    return r
            return TerminationResult(False)
        else:  # "all"
            reasons = [r.reason for r in results if r.should_terminate]
            if len(reasons) == len(self._conditions):
                return TerminationResult(True, "; ".join(reasons))
            return TerminationResult(False)
