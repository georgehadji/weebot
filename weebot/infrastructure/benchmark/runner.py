"""BenchmarkRunner — execute suites against a model and produce ModelQualityProfile.

Design:

1. Collect all ``BenchmarkSuite`` items.
2. Send each prompt to the target model (via an LLM callable).
3. Score responses against expected patterns.
4. Produce a ``ModelQualityProfile`` with ``source="benchmark"``.
5. Cost guard: estimate token cost before running; abort over budget.

The runner is **deterministic for a given model** — exact same prompts and
scoring every time.  The only source of variation is the model's responses.

Usage::

    runner = BenchmarkRunner(call_llm=my_llm_chat_fn)
    profile = await runner.run("deepseek/deepseek-v4-flash")
    profile.source  # → "benchmark"
    profile.axes    # → {CapabilityAxis.CODING: 8.5, CapabilityAxis.REASONING: 7.0, ...}
"""

from __future__ import annotations

import logging
from typing import Any
from collections.abc import Callable

from weebot.config.model_registry import get_model_info
from weebot.domain.models.capability import CapabilityAxis, ModelQualityProfile
from weebot.infrastructure.benchmark.suites import ALL_SUITES, BenchmarkItem, BenchmarkSuite

logger = logging.getLogger(__name__)

# Default cost ceiling in USD.  Beyond this the runner aborts.
_DEFAULT_COST_CEILING: float = 0.50

# Estimated tokens per prompt (average heuristic).
_EST_TOKENS_PER_PROMPT: int = 100
_EST_TOKENS_PER_RESPONSE: int = 150


class BenchmarkRunner:
    """Execute benchmark suites against a model.

    Args:
        call_llm: Async callable ``(model_id, messages) -> str`` that returns
            the model's response text.  Called once per suite item.
        cost_ceiling: Maximum spend per run (USD).  Default 0.50.
        max_retries: Number of retries per prompt on failure.
    """

    def __init__(
        self,
        call_llm: Callable[..., Any],
        cost_ceiling: float = _DEFAULT_COST_CEILING,
        max_retries: int = 1,
    ) -> None:
        self._call_llm = call_llm
        self._cost_ceiling = cost_ceiling
        self._max_retries = max_retries

    async def run(
        self, model_id: str, suites: list[BenchmarkSuite] | None = None
    ) -> ModelQualityProfile | None:
        """Run all (or specified) suites against *model_id*.

        Returns a ``ModelQualityProfile`` with ``source="benchmark"``,
        or ``None`` if the cost guard aborts or all items fail.

        Args:
            model_id: The model to benchmark.
            suites: Subset of suites to run.  Defaults to all suites.

        Raises:
            CostGuardError: If the estimated cost exceeds the ceiling.
        """
        suites = suites or ALL_SUITES

        # Cost guard: estimate before running
        estimated_cost = self._estimate_cost(model_id, suites)
        if estimated_cost > self._cost_ceiling:
            raise CostGuardError(
                f"Estimated cost ${estimated_cost:.4f} exceeds ceiling "
                f"${self._cost_ceiling:.2f} for {model_id}"
            )
        logger.info(
            "Benchmark: running %d suites for %s (est. $%.4f)",
            len(suites),
            model_id,
            estimated_cost,
        )

        # Execute each suite: collect responses and score
        axes: dict[CapabilityAxis, float] = {}
        total_duration = 0.0
        total_items = 0

        for suite in suites:
            responses: list[str] = []
            for item in suite.items:
                resp = await self._call_item(model_id, item)
                if resp is not None:
                    responses.append(resp)
                else:
                    responses.append("")  # empty response = 0 score
                total_items += 1

            score = suite.score_all(responses)
            try:
                axis = CapabilityAxis(suite.axis)
                axes[axis] = round(score, 1)
                logger.debug("Benchmark %s/%s: %.1f/10", model_id, suite.axis, score)
            except ValueError:
                logger.warning("Unknown axis '%s' — skipping", suite.axis)

        if not axes:
            logger.warning("Benchmark: no valid axes scored for %s", model_id)
            return None

        return ModelQualityProfile(model_id=model_id, axes=axes, source="benchmark")

    async def _call_item(self, model_id: str, item: BenchmarkItem) -> str | None:
        """Send a single prompt and return the response text.

        Retries on failure up to ``_max_retries`` times.
        """
        for attempt in range(self._max_retries + 1):
            try:
                messages = [{"role": "user", "content": item.prompt}]
                resp = await self._call_llm(model_id, messages)
                if isinstance(resp, str):
                    return resp
                # Handle structured responses
                content = getattr(resp, "content", None)
                if content:
                    return content
                return str(resp)
            except Exception as exc:
                if attempt < self._max_retries:
                    logger.debug(
                        "Benchmark retry %d/%d for %s: %s",
                        attempt + 1,
                        self._max_retries,
                        model_id,
                        exc,
                    )
                else:
                    logger.warning(
                        "Benchmark failed for %s after %d retries: %s",
                        model_id,
                        self._max_retries,
                        exc,
                    )
        return None

    def _estimate_cost(self, model_id: str, suites: list[BenchmarkSuite]) -> float:
        """Estimate the dollar cost of running *suites* against *model_id*.

        Returns 0 if the model's cost info is unavailable (conservative —
        allows the run rather than blocking).
        """
        info = get_model_info(model_id)
        if info is None:
            return 0.0

        total_prompts = sum(len(s.items) for s in suites)
        input_tokens = total_prompts * _EST_TOKENS_PER_PROMPT
        output_tokens = total_prompts * _EST_TOKENS_PER_RESPONSE
        return info.calculate_cost(input_tokens, output_tokens)

    def get_total_items(self, suites: list[BenchmarkSuite] | None = None) -> int:
        """Return the total number of benchmark items across *suites*."""
        return sum(len(s.items) for s in (suites or ALL_SUITES))

    @property
    def cost_ceiling(self) -> float:
        return self._cost_ceiling


class CostGuardError(Exception):
    """Raised when estimated benchmark cost exceeds the configured ceiling."""

    pass
