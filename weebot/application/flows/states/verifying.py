"""VerifyingState — Chain-of-Verification fact-checking after summarization.

Implements the CoVe pattern (Dhuliawala et al., 2023):
1. Generate verification questions from the summary
2. Answer each question INDEPENDENTLY (no shared context with draft)
3. If contradictions found, revise the summary
4. Emit VerificationEvents for audit

Factored verification: each question is answered in its own LLM call
without seeing the original summary.  This prevents the LLM from
repeating hallucinations (the paper's key finding).
"""
from __future__ import annotations

import logging
from typing import Optional

from weebot.application.flows.states.base import FlowState, AgentStatus
from weebot.domain.models.event import VerificationEvent

_log = logging.getLogger(__name__)


class VerifyingState(FlowState):
    """CoVe verification state — fact-checks the summary before completion.

    Controlled by env var ``WEEBOT_COVE_ENABLED`` (default: True).
    Set to ``false`` to skip verification and proceed directly to Completed.
    """

    status = AgentStatus.VERIFYING  # type: ignore[assignment]

    def __init__(self, max_questions: int = 3):
        self._max_questions = max_questions

    async def execute(self, flow, prompt: str = ""):
        """Run the CoVe verification pipeline.

        Args:
            flow: The PlanActFlow instance (provides llm, session, plan).
            prompt: Not used — verification runs on the flow's current plan/session.
        """
        import os

        # ── Feature toggle ──────────────────────────────────────────
        enabled = os.getenv("WEEBOT_COVE_ENABLED", "true").lower() in ("true", "1", "yes")
        if not enabled:
            _log.debug("CoVe disabled — skipping verification")
            from weebot.application.flows.states.completed import CompletedState
            flow.set_state(CompletedState())
            return

        num_questions = int(os.getenv("WEEBOT_COVE_QUESTIONS", str(self._max_questions)))

        # ── Get the summary to verify ───────────────────────────────
        plan = flow._plan
        if plan is None:
            _log.debug("No plan to verify — skipping")
            from weebot.application.flows.states.completed import CompletedState
            flow.set_state(CompletedState())
            return

        # Collect completed step results as the "summary" to fact-check
        completed = [s for s in plan.steps if hasattr(s.status, "value") and s.status.value == "completed"]
        if not completed:
            _log.debug("No completed steps to verify — skipping")
            from weebot.application.flows.states.completed import CompletedState
            flow.set_state(CompletedState())
            return

        summary = "\n".join(
            f"Step {s.id}: {s.description}\nResult: {s.result or '(no result)'}"
            for s in completed[-5:]  # Last 5 steps
        )

        # ── Step 1: Generate verification questions ─────────────────
        questions = await self._generate_questions(flow, summary, num_questions)
        if not questions:
            _log.debug("No verification questions generated — skipping")
            from weebot.application.flows.states.completed import CompletedState
            flow.set_state(CompletedState())
            return

        # ── Step 2: Answer each independently (factored) ────────────
        inconsistencies: list[tuple[str, str, str]] = []  # (question, answer, original_claim)
        for question in questions:
            answer = await self._answer_independently(flow, question)
            consistent = await self._check_consistency(flow, question, answer, summary)

            yield VerificationEvent(
                step_id="verify",
                question=question,
                answer=answer,
                consistent=consistent,
            )

            if not consistent:
                # Find which claim this question was about
                inconsistencies.append((question, answer, summary[:200]))

        # ── Step 3: Revise if needed ────────────────────────────────
        if inconsistencies:
            _log.info(
                "CoVe found %d inconsistencies — revising summary",
                len(inconsistencies),
            )
            revised = await self._revise_summary(flow, summary, inconsistencies)
            if revised:
                # Store revised summary back on the last completed step
                last = completed[-1]
                setattr(last, "result", revised[:500])
        else:
            _log.info("CoVe verification passed — no inconsistencies")

        # ── Transition to Completed ─────────────────────────────────
        from weebot.application.flows.states.completed import CompletedState
        flow.set_state(CompletedState())

    # ── Internal ─────────────────────────────────────────────────────

    async def _generate_questions(self, flow, summary: str, n: int) -> list[str]:
        """Generate verification questions from the summary."""
        prompt = (
            f"Given this task summary, list up to {n} specific fact-checking "
            f"questions that could verify its accuracy.  Each question should "
            f"target a concrete claim (dates, counts, names, file paths, results).\n\n"
            f"Summary:\n{summary}\n\n"
            f"Verification questions (one per line, no numbering):"
        )
        try:
            response = await flow._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,  # deterministic for verification
                max_tokens=200,
            )
            content = response.content or ""
            questions = [
                line.strip("-• "*3).strip()
                for line in content.splitlines()
                if line.strip() and "?" in line
            ]
            return questions[:n]
        except Exception:
            _log.debug("Failed to generate verification questions", exc_info=True)
            return []

    async def _answer_independently(self, flow, question: str) -> str:
        """Answer a verification question WITHOUT seeing the original summary."""
        try:
            response = await flow._llm.chat(
                messages=[{"role": "user", "content": question}],
                temperature=0.0,
                max_tokens=150,
            )
            return (response.content or "").strip()
        except Exception:
            _log.debug("Failed to answer verification question", exc_info=True)
            return "(verification failed)"

    async def _check_consistency(
        self, flow, question: str, answer: str, summary: str
    ) -> bool:
        """Check if the independent answer is consistent with the summary."""
        prompt = (
            f"Original claim (from summary):\n{summary[:300]}\n\n"
            f"Verification question: {question}\n"
            f"Independent answer: {answer}\n\n"
            f"Is the independent answer CONSISTENT with the original claim? "
            f"Answer only YES or NO."
        )
        try:
            response = await flow._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=10,
            )
            return "yes" in (response.content or "").lower()
        except Exception:
            return True  # Assume consistent on failure — don't block completion

    async def _revise_summary(
        self, flow, summary: str, inconsistencies: list[tuple[str, str, str]]
    ) -> str | None:
        """Revise the summary based on verified inconsistencies."""
        inc_block = "\n".join(
            f"Q: {q}\nA: {a}\n" for q, a, _ in inconsistencies
        )
        prompt = (
            f"Original summary:\n{summary}\n\n"
            f"The following claims were found to be inconsistent:\n{inc_block}\n\n"
            f"Revise the summary to correct only the inconsistent claims. "
            f"Keep everything else unchanged."
        )
        try:
            response = await flow._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=500,
            )
            return (response.content or "").strip()
        except Exception:
            _log.debug("Failed to revise summary", exc_info=True)
            return None
