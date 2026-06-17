"""Context Manager — orchestrates context compression at flow turn boundaries.

Wraps the selected context engine (e.g., LossyContextCompressor) and
hooks into PlanActFlow turn boundaries to manage the token budget.
"""
from __future__ import annotations

import logging
from typing import Any

from weebot.application.ports.context_engine_port import IContextEnginePort
from weebot.domain.models.context import ContextBudget
from weebot.config.settings import WeebotSettings

logger = logging.getLogger(__name__)


class ContextManager:
    """Orchestrates context management across flow turns.

    Usage in a flow:
        mgr = ContextManager(engine)
        messages = [...]

        # Before LLM call:
        msg_list = [m.to_dict() for m in messages]  # or whatever format
        result = await mgr.prepare(msg_list)
        if result is not None:
            # Apply compression — inject summary, drop old messages
            messages = apply_compression(messages, result)

        # Then make the LLM call with messages
    """

    def __init__(
        self,
        engine: IContextEnginePort,
        budget: ContextBudget | None = None,
    ) -> None:
        self._engine = engine
        self._budget = budget or self._budget_from_settings()
        self._compression_count = 0

    @staticmethod
    def _budget_from_settings() -> ContextBudget:
        """Read budget defaults from WeebotSettings."""
        try:
            settings = WeebotSettings()
            return ContextBudget(
                max_tokens=settings.context_compression_threshold,
                protect_last_n=settings.context_compression_protect_last_n,
                target_ratio=settings.context_compression_target_ratio,
            )
        except Exception:
            return ContextBudget()

    async def prepare(
        self,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Prepare messages for an LLM call — may compress if over budget.

        Args:
            messages: Current message list as dicts.

        Returns:
            A dict with compression result info, or None if no compression needed.
            The caller is responsible for applying the changes.
        """
        if self._budget.max_tokens <= 0:
            return None

        token_count = await self._engine.get_token_count(messages)

        if token_count <= self._budget.max_tokens:
            return None  # No compression needed

        should = await self._engine.should_compress(messages, token_count)
        if not should:
            return None

        result = await self._engine.compress(messages, self._budget)
        self._compression_count += 1

        logger.info(
            "ContextManager: compressed %d→%d tokens (count: %d)",
            result.original_token_count, result.compressed_token_count,
            self._compression_count,
        )

        return {
            "compression_result": result,
            "summary": result.summary,
            "original_token_count": result.original_token_count,
            "compressed_token_count": result.compressed_token_count,
            "retained_count": result.retained_count,
            "discarded_count": result.discarded_count,
        }

    @property
    def compression_count(self) -> int:
        return self._compression_count
