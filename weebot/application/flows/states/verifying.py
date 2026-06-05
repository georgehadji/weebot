"""Verifying state — Chain-of-Verification (CoVe) for Plan-Act Flow.

Inserts between Executing and Summarizing.  When all steps complete,
collects the final assistant response, runs CoVe to check for factual
hallucinations, and emits a corrected MessageEvent if issues are found.

Reference: Dhuliawala et al. (2023) — Chain-of-Verification Reduces
Hallucination in Large Language Models (arXiv:2309.11495).
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states.base import AgentStatus, FlowState
from weebot.application.services.chain_of_verification import (
    ChainOfVerificationService,
)
from weebot.domain.models.event import AgentEvent, ErrorEvent, MessageEvent

logger = logging.getLogger(__name__)


def _replace_last_assistant_message(session, new_text: str):
    """Return a new session with the last assistant MessageEvent's message replaced.

    Does not mutate the original session.  Falls back to the original session
    if no assistant message is found.
    """
    events = list(session.events)
    for i in range(len(events) - 1, -1, -1):
        event = events[i]
        if isinstance(event, MessageEvent) and event.role == "assistant":
            events[i] = event.model_copy(update={"message": new_text})
            return session.model_copy(update={"events": events})
    return session


class VerifyingState(FlowState):
    """Performs Chain-of-Verification on the final assistant response.

    Transitions to SummarizingState when verification is complete (or
    skipped due to no LLM port being available).
    """
    status = AgentStatus.VERIFYING

    async def execute(
        self, context: PlanActFlow, prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        from weebot.application.flows.states.summarizing import SummarizingState

        # ── Collect the baseline response (last assistant message) ──
        baseline = self._collect_baseline(context)
        if not baseline or not baseline.strip():
            logger.info("CoVe: no baseline response to verify — skipping")
            context.set_state(SummarizingState())
            return

        # ── CoVe enabled check ──
        import os as _os
        if _os.environ.get("WEEBOT_COVE_ENABLED", "").lower() in ("false", "0", "no"):
            logger.info("CoVe: disabled via WEEBOT_COVE_ENABLED — skipping")
            context.set_state(SummarizingState())
            return

        # ── Get LLM for verification ──
        llm = self._resolve_llm(context)
        if llm is None:
            logger.info("CoVe: no LLM port available — skipping")
            context.set_state(SummarizingState())
            return

        # ── Run CoVe ──
        cove = ChainOfVerificationService(llm)
        try:
            task_prompt = (
                context._session.context.get("original_task", "") or prompt
            )
            corrected, inconsistencies = await cove.verify(
                query=task_prompt,
                response=baseline,
                max_questions=5,
            )

            if inconsistencies:
                logger.info(
                    "CoVe: corrected %d inconsistencies in final response",
                    len(inconsistencies),
                )
                for inc in inconsistencies:
                    logger.info(
                        "  Claim: %s → %s (via: %s)",
                        inc.get("claim", "?"),
                        inc.get("correction", "?"),
                        inc.get("verification_question", "?"),
                    )
                context._session = _replace_last_assistant_message(
                    context._session, corrected
                )
                yield MessageEvent(
                    role="assistant",
                    message=(
                        corrected + "\n\n*[Verified: "
                        f"{len(inconsistencies)} fact(s) corrected]*"
                    ),
                )
            else:
                logger.info("CoVe: no inconsistencies found")

        except Exception as exc:
            logger.warning("CoVe verification failed: %s", exc)
            yield ErrorEvent(error=f"Verification failed: {exc}")
            yield MessageEvent(role="assistant", message=baseline)

        finally:
            # ── Transition to summary (always, even if consumer breaks) ──
            context.set_state(SummarizingState())

    @staticmethod
    def _collect_baseline(context: PlanActFlow) -> str:
        """Extract the last assistant message from the session events."""
        for event in reversed(context._session.events):
            if isinstance(event, MessageEvent) and event.role == "assistant":
                return event.message
        return ""

    @staticmethod
    def _resolve_llm(context: PlanActFlow):
        """Get an LLMPort from the PlanActFlow's injected LLM reference."""
        if hasattr(context, "_llm") and context._llm is not None:
            return context._llm
        # Fallback: use the executor's LLM if flow-level LLM is missing
        if hasattr(context, "_executor") and hasattr(context._executor, "_llm"):
            return context._executor._llm
        return None
