"""MetaSelfImprover — metacognitive self-improvement wrapper.

Implements Enhancement 7 from the HyperAgents plan: wraps the SelfImprover
with a meta-review loop.  After each successful patch, a meta-review asks
whether the improvement STRATEGY itself should be updated.  This closes
the self-referential loop from the HyperAgents paper.

Gated behind WEEBOT_METACOGNITIVE_IMPROVEMENT feature flag (default: OFF).
All meta-edits are logged to MetaImprovementLog for auditability.

When enabled, the SelfImprover's allowlist is expanded to include itself
and this wrapper, enabling true self-referential improvement.
"""
from __future__ import annotations

import logging
from typing import Optional

from weebot.application.ports.llm_port import LLMPort
from weebot.config import feature_flags
from weebot.config.model_refs import MODEL_BUDGET
from weebot.infrastructure.persistence.meta_improvement_log import MetaImprovementLog

logger = logging.getLogger(__name__)

_META_REVIEW_PROMPT = """Review this SelfImprover patch and decide if the IMPROVEMENT STRATEGY
itself should be updated.

Patch target: {target_file}
Patch summary: {change_summary}
Strategy used: {strategy}

Answer as JSON:
{{
  "should_update_strategy": true/false,
  "confidence": 0.0-1.0,
  "new_strategy": "if should_update_strategy is true, the improved strategy text"
}}

Only recommend updating the strategy if there is a clear, concrete
improvement to the SelfImprover's approach — not for trivial tweaks."""


class MetaSelfImprover:
    """Wraps SelfImprover with metacognitive review.

    Usage:
        improver = MetaSelfImprover(llm=llm_port, self_improver=self_improver)

        patch = await self_improver.propose_patch(...)
        if patch and patch.applied:
            review = await improver.meta_review(patch)
            if review.should_apply:
                # Update the SelfImprover's own strategy
                ...
    """

    def __init__(
        self,
        llm: LLMPort,
        audit_log: MetaImprovementLog | None = None,
    ) -> None:
        self._llm = llm
        self._audit_log = audit_log or MetaImprovementLog()

    @property
    def is_enabled(self) -> bool:
        """Whether metacognitive improvement is currently active."""
        return feature_flags.METACOGNITIVE_IMPROVEMENT_ENABLED

    async def meta_review(
        self,
        target_file: str,
        change_summary: str,
        strategy: str = "default",
    ) -> "MetaReviewResult":
        """Review a SelfImprover patch and optionally propose a strategy update.

        Args:
            target_file: The file that was patched.
            change_summary: What the patch changed.
            strategy: The improvement strategy that produced the patch.

        Returns:
            MetaReviewResult with should_update_strategy, confidence, and
            optional new_strategy text.
        """
        if not self.is_enabled:
            return MetaReviewResult.skip("feature flag disabled")

        user_prompt = _META_REVIEW_PROMPT.format(
            target_file=target_file,
            change_summary=change_summary,
            strategy=strategy,
        )

        try:
            resp = await self._llm.chat(
                messages=[
                    {"role": "system", "content": "You are a meta-review analyst."},
                    {"role": "user", "content": user_prompt},
                ],
                model=MODEL_BUDGET,
                temperature=TEMPERATURE_DEFAULT,
                max_tokens=MAX_TOKENS_COMPACT,
            )

            import json
            data = json.loads(resp.content or "{}")

            result = MetaReviewResult(
                should_update_strategy=data.get("should_update_strategy", False),
                confidence=data.get("confidence", 0.0),
                new_strategy=data.get("new_strategy", ""),
            )

            # Log to audit trail
            await self._audit_log.record(
                editor="MetaSelfImprover",
                target_file=target_file,
                change_summary=f"Meta-review: {change_summary[:200]}",
                rollback_info=(
                    f"should_update={result.should_update_strategy}, "
                    f"confidence={result.confidence:.2f}"
                ),
            )

            return result

        except Exception as exc:
            logger.warning("Meta-review failed: %s", exc)
            return MetaReviewResult.skip(f"LLM error: {exc}")


class MetaReviewResult:
    """Result of a meta-review of a SelfImprover patch."""

    def __init__(
        self,
        should_update_strategy: bool = False,
        confidence: float = 0.0,
        new_strategy: str = "",
        skip_reason: str = "",
    ) -> None:
        self.should_update_strategy = should_update_strategy
        self.confidence = confidence
        self.new_strategy = new_strategy
        self.skip_reason = skip_reason

    @property
    def should_apply(self) -> bool:
        """Whether the strategy update should be applied.

        Requires both the flag and high confidence (>0.8).
        """
        return (
            self.should_update_strategy
            and self.confidence > 0.8
            and bool(self.new_strategy.strip())
        )

    @classmethod
    def skip(cls, reason: str = "") -> "MetaReviewResult":
        return cls(skip_reason=reason)
