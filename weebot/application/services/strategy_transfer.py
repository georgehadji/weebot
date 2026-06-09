"""StrategyTransferService — cross-domain transfer of improvement strategies.

Implements Enhancement 6 from the HyperAgents paper: when a new domain flow
starts, this service queries for high-effectiveness improvement strategies
from different domains and formats them for injection into the planner prompt.

The planner then sees "prior experience" that guides it toward approaches
that worked well in other domains, enabling zero-shot transfer of
meta-improvement knowledge.
"""
from __future__ import annotations

import logging
from typing import Optional

from weebot.infrastructure.persistence.strategy_store import StrategyStore

logger = logging.getLogger(__name__)


class StrategyTransferService:
    """Transfers improvement strategies across domains.

    Usage:
        store = StrategyStore()
        service = StrategyTransferService(store)

        # Before planning a task in domain "math":
        strategies = await service.get_strategies_for("math")
        prompt_fragment = service.format_for_prompt(strategies)
        # Inject prompt_fragment into the planner's user message
    """

    def __init__(
        self,
        store: StrategyStore,
        min_score: float = 0.7,
        max_strategies: int = 3,
    ) -> None:
        self._store = store
        self._min_score = min_score
        self._max_strategies = max_strategies

    async def get_strategies_for(
        self, domain: str
    ) -> list:
        """Return transferable strategies for a target domain.

        Args:
            domain: The target domain (e.g., "coding", "math", "review").

        Returns:
            List of ImprovementStrategy objects from different domains
            with effectiveness_score >= min_score.
        """
        from weebot.domain.models.self_improvement import ImprovementStrategy

        strategies = await self._store.get_for_domain(
            target_domain=domain,
            min_score=self._min_score,
            limit=self._max_strategies,
        )
        if strategies:
            logger.info(
                "Found %d strategies for domain '%s' from other domains",
                len(strategies), domain,
            )
        return strategies

    def format_for_prompt(self, strategies: list) -> str:
        """Format strategies as a prompt fragment for planner injection.

        Args:
            strategies: List of ImprovementStrategy objects.

        Returns:
            A prompt string, or empty string if no strategies.
        """
        if not strategies:
            return ""

        lines = [
            "\n\n## Prior Improvement Strategies (from other domains)",
            "The following strategies were effective in different domains. "
            "Consider applying similar approaches here:",
            "",
        ]
        for i, s in enumerate(strategies, 1):
            lines.append(
                f"{i}. [Domain: {s.source_domain}, "
                f"Score: {s.effectiveness_score:.2f}] "
                f"{s.meta_agent_prompt_snippet}"
            )

        return "\n".join(lines)

    async def record_strategy(
        self,
        source_domain: str,
        prompt_snippet: str,
        score: float,
        target_domain: str | None = None,
    ) -> str:
        """Persist a new improvement strategy after a successful epoch.

        Args:
            source_domain: Domain where the strategy was discovered.
            prompt_snippet: The improvement instruction text.
            score: How effective the strategy was (0..1).
            target_domain: Optional specific target domain (None = domain-agnostic).

        Returns:
            The new strategy_id.
        """
        from weebot.domain.models.self_improvement import ImprovementStrategy

        strategy = ImprovementStrategy(
            source_domain=source_domain,
            target_domain=target_domain,
            meta_agent_prompt_snippet=prompt_snippet,
            effectiveness_score=score,
            transfer_count=0,
        )
        sid = await self._store.insert(strategy)
        logger.info(
            "Recorded improvement strategy %s from domain '%s' (score: %.2f)",
            sid, source_domain, score,
        )
        return sid
