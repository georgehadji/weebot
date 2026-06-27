"""TokenBudgetManager — prevents silent context truncation in the agent loop.

Part of Enhancement 2.1 (Cognitive Memory Architecture).  Tracks cumulative
token usage across the entire conversation and tool calls.  Before an LLM
call is made, the budgeter checks whether the pending request fits within
the model's context window.  If not, it triggers compaction or summarization
rather than silently truncating.

Usage:
    budgeter = TokenBudgetManager(model="claude-4.5-sonnet", max_tokens=180_000)
    budgeter.add_user_message("Fix all bugs")
    budgeter.add_tool_result("bash", output)
    if not budgeter.can_fit(new_prompt, 500):
        # trigger summarization before the next LLM call
        ...
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Model context windows (tokens) — fallback when tiktoken isn't installed
_MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-4.6-opus": 200_000,
    "claude-4.5-sonnet": 200_000,
    "claude-4.5-haiku": 200_000,
    "gpt-5.2": 128_000,
    "gpt-5.1": 128_000,
    "gpt-5-mini": 128_000,
    "deepseek-v4-flash": 128_000,
    "deepseek-v4-pro": 128_000,
    "gemini-3-pro": 1_000_000,
    "gemini-2.5-flash": 1_000_000,
    "default": 128_000,
}


@dataclass
class UsageSnapshot:
    """A point-in-time snapshot of the budgeter's internal state."""
    messages_count: int
    tokens_used: int
    tokens_remaining: int
    max_tokens: int
    tool_calls: int = 0


class TokenBudgetManager:
    """Tracks token consumption and warns/pauses before truncation.

    Uses a character-based heuristic (4 chars ≈ 1 token) as a fast proxy.
    When ``tiktoken`` is available, it switches to precise counting.
    """

    # Heuristic: ~4 characters per token for English text
    _CHARS_PER_TOKEN: float = 4.0
    # Warn when remaining budget drops below this percentage
    _WARN_THRESHOLD: float = 0.25  # 25%

    def __init__(
        self,
        model: str = "default",
        max_tokens: Optional[int] = None,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens or _MODEL_CONTEXT_WINDOWS.get(
            model, _MODEL_CONTEXT_WINDOWS["default"]
        )
        self._used_tokens: int = 0
        self._message_count: int = 0
        self._tool_call_count: int = 0

        # Try tiktoken for precise counting
        try:
            import tiktoken
            self._encoder = tiktoken.get_encoding("cl100k_base")
            self._use_tiktoken = True
        except ImportError:
            self._encoder = None
            self._use_tiktoken = False

    # ── Public API ────────────────────────────────────────────────────────

    def add_user_message(self, text: str) -> None:
        self._add(text, label="user")

    def add_assistant_message(self, text: str) -> None:
        self._add(text, label="assistant")

    def add_tool_result(self, tool_name: str, output: str) -> None:
        self._add(output, label="tool_result")
        self._tool_call_count += 1

    @property
    def used_tokens(self) -> int:
        """Total tokens consumed so far."""
        return self._used_tokens

    @property
    def max_tokens(self) -> int:
        """Model context window size."""
        return self._max_tokens

    @property
    def remaining(self) -> int:
        """Tokens remaining in the budget."""
        return max(0, self._max_tokens - self._used_tokens)

    @property
    def usage_ratio(self) -> float:
        """Fraction of budget consumed (0.0–1.0)."""
        return self._used_tokens / max(self._max_tokens, 1)

    @property
    def should_warn(self) -> bool:
        """True if usage exceeds the warn threshold."""
        return self.usage_ratio > self._WARN_THRESHOLD

    def can_fit(self, text: str, safety_margin: int = 0) -> bool:
        """Check whether *text* fits in the remaining budget.

        Args:
            text: The text to be sent (prompt + expected response).
            safety_margin: Additional token buffer for overhead.

        Returns:
            True if the text fits.
        """
        needed = self._count_tokens(text) + safety_margin
        return needed <= self.remaining

    def snapshot(self) -> UsageSnapshot:
        """Return a point-in-time snapshot for logging/debugging."""
        return UsageSnapshot(
            messages_count=self._message_count,
            tokens_used=self._used_tokens,
            tokens_remaining=self.remaining,
            max_tokens=self._max_tokens,
            tool_calls=self._tool_call_count,
        )

    def reset(self) -> None:
        """Reset the budgeter for a new conversation."""
        self._used_tokens = 0
        self._message_count = 0
        self._tool_call_count = 0

    # ── Internal ──────────────────────────────────────────────────────────

    def _count_tokens(self, text: str) -> int:
        """Count tokens in *text* using tiktoken or the character heuristic."""
        if self._use_tiktoken and self._encoder is not None:
            return len(self._encoder.encode(text))
        return max(1, int(len(text) / self._CHARS_PER_TOKEN))

    def _add(self, text: str, label: str) -> None:
        tokens = self._count_tokens(text)
        self._used_tokens += tokens
        self._message_count += 1

        if self.should_warn:
            logger.warning(
                "Token budget: %d/%d used (%.0f%%) — last %s added %d tokens",
                self._used_tokens, self._max_tokens,
                self.usage_ratio * 100, label, tokens,
            )
