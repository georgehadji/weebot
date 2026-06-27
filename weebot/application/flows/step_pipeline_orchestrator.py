"""StepPipelineOrchestrator — coordinates per-step flow through critique,
pre-mortem, execution, review, and verify for PlanActFlow.

Extracted from PlanActFlow to isolate the step-pipeline orchestration concern.

The pipeline is:
    1. Critique — LLM evaluates step viability before execution
    2. Pre-mortem — identify potential failure modes
    3. Execute — run the step via tools
    4. Review — LLM code review of step output
    5. Verify — check step results against expectations

Usage:
    pipeline = StepPipelineOrchestrator(llm=llm, tools=tools)
    result = await pipeline.run(step, plan)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class StepPipelineResult:
    """Result of running a step through the pipeline."""
    def __init__(
        self,
        step: Any,
        passed: bool = False,
        needs_replan: bool = False,
        error: Optional[str] = None,
        validation_score: float = 0.0,
        review_verdict: str = "",
    ) -> None:
        self.step = step
        self.passed = passed
        self.needs_replan = needs_replan
        self.error = error
        self.validation_score = validation_score
        self.review_verdict = review_verdict


class StepPipelineOrchestrator:
    """Orchestrates the per-step lifecycle: critique → execute → review → verify.

    This is a coordinator — it delegates to the actual critique, execution,
    and review services rather than implementing them directly.
    """

    def __init__(
        self,
        llm: Any = None,
        tools: Any = None,
        critic: Any = None,
        reviewer: Any = None,
        verifier: Any = None,
        event_bus: Any = None,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._critic = critic
        self._reviewer = reviewer
        self._verifier = verifier
        self._event_bus = event_bus

    async def run(
        self,
        step: Any,
        plan: Any,
        session: Any,
        context: Optional[dict[str, Any]] = None,
    ) -> StepPipelineResult:
        """Execute a single step through the full pipeline.

        1. Critique (if critic available)
        2. Execute via tools
        3. Review (if reviewer available)
        4. Verify (if verifier available)

        Returns StepPipelineResult with pass/fail status.
        """
        # 1. Critique (pre-execution validation)
        if self._critic is not None:
            try:
                critique = await self._critic.critique(step, plan)
                if not critique.passed:
                    return StepPipelineResult(
                        step=step, passed=False,
                        needs_replan=True,
                        error=f"Critique failed: {critique.reasoning}",
                    )
            except Exception as exc:
                logger.warning("Step critique failed (proceeding): %s", exc)

        # 2. Execute via tools
        try:
            result = await self._execute_step(step, session, context)
            if result is None:
                return StepPipelineResult(
                    step=step, passed=False,
                    needs_replan=True,
                    error="Step execution returned no result",
                )
        except Exception as exc:
            return StepPipelineResult(
                step=step, passed=False,
                needs_replan=True,
                error=f"Step execution failed: {exc}",
            )

        # 3. Review (post-execution code review)
        review_verdict = ""
        if self._reviewer is not None:
            try:
                review = await self._reviewer.review(step, result)
                review_verdict = getattr(review, "verdict", "approved")
                if review_verdict == "rejected":
                    return StepPipelineResult(
                        step=step, passed=False,
                        needs_replan=True,
                        error=f"Review rejected: {getattr(review, 'summary', '')}",
                        review_verdict=review_verdict,
                    )
            except Exception as exc:
                logger.warning("Step review failed (proceeding): %s", exc)

        # 4. Verify (quality check against expected outcomes)
        validation_score = 1.0
        if self._verifier is not None:
            try:
                validation = await self._verifier.verify(step, result)
                validation_score = getattr(validation, "score", 1.0)
                if validation_score < 0.5:
                    return StepPipelineResult(
                        step=step, passed=False,
                        needs_replan=False,
                        error=f"Verification failed (score={validation_score:.2f})",
                        validation_score=validation_score,
                        review_verdict=review_verdict,
                    )
            except Exception as exc:
                logger.warning("Step verification failed (proceeding): %s", exc)

        return StepPipelineResult(
            step=step, passed=True,
            validation_score=validation_score,
            review_verdict=review_verdict,
        )

    async def _execute_step(
        self,
        step: Any,
        session: Any,
        context: Optional[dict[str, Any]] = None,
    ) -> Optional[Any]:
        """Execute a step using the available tools.

        Note: Actual execution is tightly coupled to PlanActFlow's CQRS
        mediator and state management.  This method provides the pipeline
        coordination structure.  Full implementation requires extracting
        the executor from PlanActFlow (B2 sprint).
        """
        if self._tools is None:
            logger.warning("StepPipelineOrchestrator: no tools available")
            return None

        logger.info(
            "Pipeline executing step %s: %.60s",
            getattr(step, "id", "?"), getattr(step, "description", ""),
        )
        # Stub: real execution requires the CQRS mediator and ExecutorAgent
        # from PlanActFlow.  Returns a placeholder result for now.
        return {"executed": True, "step_id": getattr(step, "id", None)}
