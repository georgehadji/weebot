"""Context engine port — pluggable context compression and management.

Implemented by different compression strategies (e.g., lossy summarize,
drop oldest) and wrapped by ContextManager which integrates into flows.
"""
from __future__ import annotations

from typing import Any, Protocol

from weebot.domain.models.context import CompressionResult, ContextBudget


class IContextEnginePort(Protocol):
    """Protocol for context compression engines.

    Each engine implements ``compress`` and ``should_compress``.
    The ``compress`` method returns a ``CompressionResult`` with the
    compressed summary and counts.
    """

    async def should_compress(self, messages: list[dict[str, Any]], token_count: int) -> bool:
        """Determine if compression should be triggered.

        Args:
            messages: Current message list.
            token_count: Estimated token count of the messages.

        Returns:
            True if compression should proceed.
        """
        ...

    async def compress(
        self,
        messages: list[dict[str, Any]],
        budget: ContextBudget | None = None,
    ) -> CompressionResult:
        """Compress messages according to the budget.

        Args:
            messages: Full message list (system + context + conversational).
            budget: Budget parameters (threshold, protect_last_n, target_ratio).

        Returns:
            CompressionResult with summary and counts.
        """
        ...

    async def get_token_count(self, messages: list[dict[str, Any]]) -> int:
        """Estimate token count for a message list.

        Args:
            messages: Message list to estimate.

        Returns:
            Estimated token count (best-effort).
        """
        ...
