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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from weebot.application.ports.strategy_store_port import StrategyStorePort

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
        self, store: StrategyStorePort, min_score: float = 0.7, max_strategies: int = 3
    ) -> None:
        if store is None:
            raise TypeError(
                "StrategyTransferService requires a store. "
                "Inject a StrategyStorePort adapter via the DI container."
            )
        self._store = store
        self._min_score = min_score
        self._max_strategies = max_strategies

    async def get_strategies_for(self, domain: str) -> list:
        """Return transferable strategies for a target domain.

        Args:
            domain: The target domain (e.g., "coding", "math", "review").

        Returns:
            List of ImprovementStrategy objects from different domains
            with effectiveness_score >= min_score.
        """

        strategies = await self._store.get_for_domain(
            target_domain=domain, min_score=self._min_score, limit=self._max_strategies
        )
        if strategies:
            logger.info(
                "Found %d strategies for domain '%s' from other domains", len(strategies), domain
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

    async def record_success(self, task: str, plan: Any) -> None:
        """Record a fully successful plan's approach under the task's category.

        One row per task (the id is the task hash), so re-runs update it. Never
        raises: learning must not fail a completed run.
        """
        try:
            if not task or plan is None or not plan.steps or not plan.is_successful():
                return
            from weebot.application.services.task_model_router import category_for_step
            from weebot.domain.services.plan_template_cache import compute_task_hash

            approach = "; ".join(s.description[:60] for s in plan.steps)[:300]
            await self.record_strategy(
                source_domain=category_for_step(task),
                prompt_snippet=f"For '{task[:80]}': {approach}",
                score=1.0,
                strategy_id=compute_task_hash(task),
            )
        except Exception:
            logger.warning("Recording a strategy failed", exc_info=True)

    async def notes_for(self, task: str, limit: int = 2) -> list[str]:
        """Planner notes: approaches that worked in OTHER task categories; [] on any problem."""
        try:
            from weebot.application.services.task_model_router import category_for_step

            domain = category_for_step(task)
            strategies = (await self.get_strategies_for(domain))[:limit]
        except Exception as exc:
            logger.debug("Strategy lookup skipped: %s", exc)
            return []
        return [
            f"An approach that worked on a {s.source_domain} task: {s.meta_agent_prompt_snippet}"
            for s in strategies
        ]

    async def record_strategy(
        self,
        source_domain: str,
        prompt_snippet: str,
        score: float,
        target_domain: str | None = None,
        strategy_id: str | None = None,
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
            strategy_id=strategy_id or "",
            source_domain=source_domain,
            target_domain=target_domain,
            meta_agent_prompt_snippet=prompt_snippet,
            effectiveness_score=score,
            transfer_count=0,
        )
        sid = await self._store.insert(strategy)
        logger.info(
            "Recorded improvement strategy %s from domain '%s' (score: %.2f)",
            sid,
            source_domain,
            score,
        )
        return sid
