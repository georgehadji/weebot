"""ProductGateState — pre-flight product thinking before plan creation.

Runs the product-mode pre-flight checklist on the user's prompt *before*
any plan is created.  If confidence is high, stores the ProductContext and
transitions to PlanningState.  If confidence is low, pauses for user
clarification and re-runs with the enriched context.

Follows the PlanReviewState pause-and-resume pattern:
    weebot/application/flows/states/plan_review.py

Sits between FlowRouter and PlanningState in the pipeline:

    FlowRouter → ProductGateState → PlanningState → ...

Skipped for:
    - Trivial tasks (under 6 words or first-word matching SIMPLE verbs)
    - Tasks where WEEBOT_PRODUCT_MODE is disabled
    - Resume/re-plan sessions (only runs on fresh PlanningState tasks)

product-mode reference:
    https://github.com/sohaibt/product-mode
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states.base import AgentStatus, FlowState
from weebot.domain.models.event import (
    AgentEvent,
    ProductGateReviewEvent,
    ThoughtEvent,
    WaitForUserEvent,
)
from weebot.domain.models.product_context import ProductContext

logger = logging.getLogger(__name__)

# Minimum word count to trigger the gate — very short prompts skip it
_MIN_PROMPT_WORDS = 6


def _is_trivial(prompt: str) -> bool:
    """Heuristic to skip the gate for obvious one-action prompts.

    Matches scope_classifier's SIMPLE patterns cheaply.
    """
    words = len(prompt.strip().lower().split())
    if words < _MIN_PROMPT_WORDS:
        return True
    # Single verb patterns
    trivial_pats = (
        "read", "show", "display", "cat", "list", "ls", "dir",
        "run", "test", "check", "verify",
        "what", "who", "when", "where", "how", "why",
        "tell", "explain", "describe", "define",
    )
    first = prompt.strip().lower().split()[0] if prompt.strip() else ""
    return first in trivial_pats


class ProductGateState(FlowState):
    """Runs the product-mode pre-flight checklist before planning.

    Args:
        resume_with: When the gate is re-entered after user clarification,
                     this contains the user's response to the WaitForUserEvent.
    """

    status = AgentStatus.PLANNING  # Planning sub-phase — reuses existing status

    def __init__(self, resume_with: str = "") -> None:
        self._resume_with = resume_with

    async def execute(
        self, context: "PlanActFlow", prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        from weebot.application.flows.states.planning import PlanningState
        from weebot.application.services.product_gate_analyzer import ProductGateAnalyzer

        # ── Skip check: trivial prompts bypass the gate ───────────
        if not self._resume_with and _is_trivial(prompt):
            logger.debug("Product gate skipped: trivial prompt (%d words)", len(prompt.split()))
            context.set_state(PlanningState())
            return

        # ── Empty prompt guard ─────────────────────────────────────
        if not prompt.strip() and not self._resume_with:
            logger.debug("Product gate skipped: empty prompt")
            context.set_state(PlanningState())
            return

        # ── Resolve the effective prompt ──────────────────────────
        # If this is a resume after user clarification, concatenate the
        # original prompt with the user's clarification response.
        effective_prompt = prompt
        original_task = context._session.context.get("_original_task", "")
        if self._resume_with and original_task:
            effective_prompt = f"{original_task}\n\nAdditional context from user: {self._resume_with}"
        elif self._resume_with:
            effective_prompt = f"{prompt}\n\nAdditional context from user: {self._resume_with}"
        elif original_task and not effective_prompt.strip():
            effective_prompt = original_task

        # ── Run the analyzer ──────────────────────────────────────
        # NOTE: context._model may be None here because context-aware
        # model selection runs later in PlanningState. The LLM adapter
        # resolves the actual model internally; we capture whatever is
        # configured at this point for audit.
        _raw_model = context._model
        model_id = _raw_model if isinstance(_raw_model, str) else str(_raw_model or "")
        analyzer = ProductGateAnalyzer(llm=context._llm)
        product_ctx = await analyzer.analyze(effective_prompt, model_id=model_id)

        # ── Low confidence → pause for user clarification ─────────
        if not analyzer.is_confident(product_ctx):
            low_fields = analyzer.get_low_confidence_fields(product_ctx)
            questions = analyzer.generate_clarification_questions(product_ctx)
            logger.info(
                "Product gate: low confidence (%.2f) — pausing for clarification on: %s",
                product_ctx.overall_confidence, low_fields,
            )

            # Emit partial context for observability
            yield ProductGateReviewEvent(
                product_context=product_ctx.model_dump(mode="json"),
                low_confidence_fields=low_fields,
                clarification_questions=questions,
            )

            # Mark gate as pending in session context so FlowRouter re-enters this state
            _new_extra = {**context._session.context.extra, "_product_gate_pending": True}
            _new_ctx = context._session.context.model_copy(update={"extra": _new_extra})
            context._session = context._session.model_copy(update={"context": _new_ctx})

            # Mark session as WAITING so resume works even if the caller
            # is killed before processing the WaitForUserEvent.
            from weebot.domain.models.session import SessionStatus
            context._session = context._session.set_status(SessionStatus.WAITING)

            # Build question text for the user
            q_block = "\n".join(f"- {q}" for q in questions) if questions else (
                "Your request was too vague to plan confidently. "
                "Could you provide more detail on what you need?"
            )
            yield WaitForUserEvent(
                question=(
                    f"I need a bit more clarity before planning:\n\n"
                    f"{q_block}\n\n"
                    f"Please provide more details and I'll refine the plan."
                )
            )
            return  # Don't transition — flow pauses on WaitForUserEvent

        # ── High confidence → store ProductContext, proceed to planning ──
        _extra = dict(context._session.context.extra)
        _extra["product_context"] = product_ctx.model_dump(mode="json")
        _extra.pop("_product_gate_pending", None)  # Clear any pending flag
        _new_ctx = context._session.context.model_copy(update={"extra": _extra})
        context._session = context._session.model_copy(update={"context": _new_ctx})

        logger.info(
            "Product gate passed (confidence: %.2f) — proceeding to planning",
            product_ctx.overall_confidence,
        )

        # Yield product context as a thought so the user sees the framing.
        # NOTE: yielding here triggers prompt_consumed in PlanActFlow.run(),
        # but PlanningState falls back to _original_task in session context
        # when prompt is empty — see the prompt fallback in planning.py.
        yield ThoughtEvent(
            step_id="product_gate",
            thought=(
                f"**Problem:** {product_ctx.problem}\n"
                f"**Why now:** {product_ctx.why_now}\n"
                f"**Scope:** {product_ctx.scope}\n"
                f"**Success metric:** {product_ctx.success_metric}\n"
                f"**Reversibility:** {product_ctx.reversibility}\n"
                + (f"\n**Assumptions:**\n" + "\n".join(
                    f"- [{a.status}] {a.text}" for a in product_ctx.assumptions
                ) if product_ctx.assumptions else "")
                + f"\n\n**Confidence:** {product_ctx.overall_confidence:.0%}"
            ),
        )

        context.set_state(PlanningState())
