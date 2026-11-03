"""Loop detectors for one executor step (H11).

Each detector is a small object with its own state and an ``observe`` that returns a verdict
(or a value) and never raises. ``IterationGuard`` composes them; ``GuardConfig`` holds every
number, so nothing is duplicated between the guard and the executor.
"""

from __future__ import annotations

import hashlib
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class Verdict(Enum):
    NUDGE = "nudge"
    STOP = "stop"
    RETRY = "retry"


@dataclass(frozen=True)
class GuardVerdict:
    kind: Verdict
    message: str


@dataclass(frozen=True)
class GuardConfig:
    # 24, not 12: see the note in _iteration_guard.py.
    max_tool_calls_per_step: int = 24
    max_repeated_assistant_turns: int = 2
    repeated_tool_signature_limit: int = 4
    cycle_periods: tuple[int, ...] = (2, 3, 4)
    # Results shorter than this are never stubbed; "ok" twice is not worth a pointer.
    stub_min_chars: int = 200
    empty_max_retries: int = 2
    empty_cost_ratio: float = 0.5
    empty_cost_cap_usd: float = 0.02
    repetition_threshold: float = 0.85
    repetition_window: int = 2
    # No step wall-clock budget existed before H11; this is its first value.
    wall_clock_budget_s: float = 600.0
    wrap_up_ratio: float = 0.8


class CycleDetector:
    """A tool-call signature sequence that repeats with period 2, 3 or 4 (A-B-A-B).

    The first match is a NUDGE; a match on any later call is a STOP. A period-1 repeat
    (A-A-A-A) is the signature-limit's job, so a window of one distinct call is skipped.
    """

    def __init__(self, periods: tuple[int, ...]) -> None:
        self._periods = periods
        self._seq: deque[str] = deque(maxlen=2 * max(periods))
        self._nudged = False

    def observe(self, signature: str) -> GuardVerdict | None:
        self._seq.append(signature)
        seq = list(self._seq)
        for p in self._periods:
            if len(seq) >= 2 * p and seq[-2 * p : -p] == seq[-p:] and len(set(seq[-p:])) > 1:
                return self._verdict(p)
        return None

    def _verdict(self, period: int) -> GuardVerdict:
        if self._nudged:
            return GuardVerdict(Verdict.STOP, f"tool calls cycle with period {period}")
        self._nudged = True
        return GuardVerdict(
            Verdict.NUDGE,
            f"The last tool calls repeat in a cycle of {period}. Do something different, "
            "or finish the step with what you have.",
        )


class DuplicateResultStub:
    """A result whose text equals an earlier call's becomes a pointer to that call."""

    def __init__(self, min_chars: int) -> None:
        self._min = min_chars
        self._first: dict[str, int] = {}

    def observe(self, call_no: int, text: str) -> str | None:
        if len(text) < self._min:
            return None
        digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
        first = self._first.setdefault(digest, call_no)
        return f"[identical to result of call #{first}]" if first != call_no else None


class EmptyResponseBudget:
    """Retry an empty reply while the wasted cost stays under min(ratio x step cost, cap)."""

    def __init__(self, max_retries: int, ratio: float, cap_usd: float) -> None:
        self._max, self._ratio, self._cap = max_retries, ratio, cap_usd
        self._wasted = 0.0
        self._count = 0

    def observe(self, turn_cost: float, step_cost: float) -> GuardVerdict:
        self._count += 1
        self._wasted += max(turn_cost, 0.0)
        if self._count <= self._max and self._wasted < min(self._ratio * step_cost, self._cap):
            return GuardVerdict(
                Verdict.RETRY, "Your last reply was empty. Continue the step, or give a result."
            )
        return GuardVerdict(Verdict.STOP, "empty replies with no budget left to retry")


def _grams(text: str, n: int = 5) -> set[tuple[str, ...]]:
    words = text.lower().split()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


class RepetitionGuard:
    """Assistant text that is nearly the same as one of the last turns' (5-gram Jaccard)."""

    def __init__(self, threshold: float, window: int) -> None:
        self._threshold = threshold
        self._recent: deque[set[tuple[str, ...]]] = deque(maxlen=window)

    def observe(self, text: str) -> GuardVerdict | None:
        grams = _grams(text)
        if not grams:
            return None
        similar = any(
            len(grams & prev) / len(grams | prev) >= self._threshold for prev in self._recent
        )
        self._recent.append(grams)
        if similar:
            return GuardVerdict(
                Verdict.NUDGE,
                "Your last message repeats what you already said. Take a new step or finish.",
            )
        return None


class WallClockWrapUp:
    """One wrap-up note, once the step has used its share of the wall-clock budget."""

    def __init__(
        self, budget_s: float, ratio: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = budget_s * ratio
        self._clock = clock
        self._start = clock()
        self._fired = False

    def observe(self) -> str | None:
        if self._fired or self._clock() - self._start < self._limit:
            return None
        self._fired = True
        return (
            "This step has used most of its time. Wrap up: state what is done, "
            "what is not, and finish."
        )
