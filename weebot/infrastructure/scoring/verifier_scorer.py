"""VerifierScorer — LLM-based verification with 0.0–1.0 confidence scores.

Uses a fast, cheap LLM call (e.g., GPT-4o-mini) to compare the agent's
answer against the expected answer and produce a score with reasoning.

This is the generic fallback scorer when no benchmark-specific scorer
applies. Cost: ~$0.001 per verification call.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.scoring_port import ScoringPort
from weebot.domain.models.event import TrajectoryScored
from weebot.domain.models.session import Session

logger = logging.getLogger(__name__)

VERIFIER_PROMPT = """You are an answer verifier. Compare the AGENT_ANSWER to the
EXPECTED_ANSWER and decide if it is correct.

Respond ONLY with valid JSON:
{
    "score": 0.0-1.0,
    "correct": true/false,
    "reasoning": "short explanation"
}

Rules:
- score = 1.0 if semantically equivalent
- score = 0.5 if partially correct or contains expected information
- score = 0.0 if completely wrong or unrelated
- For multiple-choice: exact match required for 1.0
- For free-form: accept paraphrases and equivalent formulations
"""


class VerifierScorer(ScoringPort):
    """ScoringPort that uses an LLM verifier to score agent answers.

    Suitable as a generic fallback for any benchmark. Uses a summary
    model (GPT-4o-mini or similar) to keep cost low.
    """

    def __init__(self, llm: LLMPort):
        self._llm = llm

    async def score(
        self,
        session: Session,
        expected_answer: Optional[str] = None,
    ) -> TrajectoryScored:
        """Score a session by asking an LLM to verify the answer."""
        # Extract final assistant message
        final_content = ""
        for event in reversed(session.events):
            if event.type == "message" and getattr(event, "role", "") == "assistant":
                final_content = getattr(event, "message", "") or ""
                break

        if expected_answer is None:
            return TrajectoryScored(
                session_id=session.id,
                task_id=session.id,
                score=0.5,
                failure_modes=["no_expected_answer"],
                success_patterns=[],
                trajectory_summary=final_content[:500],
                harness="verifier",
            )

        user_content = (
            f"EXPECTED_ANSWER:\n{expected_answer}\n\n"
            f"AGENT_ANSWER:\n{final_content}"
        )

        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": VERIFIER_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=TEMPERATURE_DETERMINISTIC,
                max_tokens=300,
            )
            data = json.loads(response.content)
            score = float(data.get("score", 0.0))
            score = max(0.0, min(1.0, score))

            failure_modes: list[str] = []
            success_patterns: list[str] = []
            if data.get("correct", False):
                success_patterns.append("verified_correct")
            else:
                failure_modes.append(data.get("reasoning", "verification_failed"))

            return TrajectoryScored(
                session_id=session.id,
                task_id=session.id,
                score=score,
                failure_modes=failure_modes,
                success_patterns=success_patterns,
                trajectory_summary=final_content[:500],
                harness="verifier",
            )
        except Exception as exc:
            logger.warning("VerifierScorer LLM call failed: %s", exc)
            return TrajectoryScored(
                session_id=session.id,
                task_id=session.id,
                score=0.0,
                failure_modes=[f"verifier_error: {exc}"],
                success_patterns=[],
                trajectory_summary=final_content[:500],
                harness="verifier",
            )
