"""TreeOfThoughtsScorer — generate and score multiple plan revision candidates.

Tree-of-Thoughts (ToT) extends the standard UpdatingState by:
1. Generating N candidate revisions of the failed step (breadth)
2. Scoring each candidate automatically (heuristic + optional LLM judge)
3. Picking the highest-scoring candidate for execution

This escapes local-minimum revision loops that plague greedy single-candidate
re-planning.  All candidates are generated in parallel (asyncio.gather).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.ports.llm_port import LLMPort

from weebot.config.constants import (
    MAX_TOKENS_BRIEF,
    MAX_TOKENS_SHORT,
    TEMPERATURE_BALANCED,
    TEMPERATURE_CREATIVE,
)

logger = logging.getLogger(__name__)

_NUM_CANDIDATES = 3
_SCORE_TIMEOUT = 5.0
_GENERATE_TIMEOUT = 15.0

# Scoring prompt — each candidate is scored 1-5 on three axes
_SCORE_SYSTEM_PROMPT = """You are a plan revision judge. Score the proposed
revision on three axes, each 1-5 (5 = best):

1. novelty: How different is this from the original approach?
2. feasibility: How likely is this to succeed given available tools?
3. specificity: How concrete and actionable are the steps?

Return ONLY valid JSON: {"novelty": 3, "feasibility": 4, "specificity": 3}"""


@dataclass
class ScoredCandidate:
    """A plan revision candidate with its aggregate score."""
    description: str
    novelty: int = 1
    feasibility: int = 1
    specificity: int = 1
    aggregate: float = 0.0

    def __post_init__(self) -> None:
        # Always derive aggregate from sub-scores (the canonical source).
        self.aggregate = (self.novelty + self.feasibility + self.specificity) / 3.0


class TreeOfThoughtsScorer:
    """Generates and scores multiple plan revision candidates.

    Args:
        llm: LLMPort for candidate generation and optional LLM scoring.
        num_candidates: Number of candidates to generate (default 3).
    """

    def __init__(
        self,
        llm: "LLMPort",
        num_candidates: int = _NUM_CANDIDATES,
    ) -> None:
        self._llm = llm
        self._num_candidates = num_candidates

    async def generate_candidates(
        self,
        step_description: str,
        failure_context: str,
    ) -> list[str]:
        """Generate N alternative approaches for the failed step.

        All candidates are generated via a single LLM call that returns
        multiple approaches in JSON.  On failure, returns a single
        fallback candidate.
        """
        prompt = (
            f"The following step failed:\n\n{step_description}\n\n"
            f"Failure context: {failure_context}\n\n"
            f"Generate {self._num_candidates} completely different approaches "
            f"to replace this step. Each must be specific and actionable.\n\n"
            f"Return ONLY valid JSON: {{\"candidates\": [\"approach 1\", \"...\"]}}"
        )
        try:
            response = await asyncio.wait_for(
                self._llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=TEMPERATURE_CREATIVE,
                    max_tokens=MAX_TOKENS_SHORT,
                ),
                timeout=_GENERATE_TIMEOUT,
            )
            raw = (response.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("\n```", 1)[0]
            data = json.loads(raw)
            candidates = data.get("candidates", [])
            if candidates:
                return candidates[:self._num_candidates]
        except Exception as exc:
            logger.debug("ToT generation failed: %s", exc)

        return [f"Alternative approach for: {step_description[:100]}"]

    async def score_candidate(
        self, candidate: str, original_step: str,
    ) -> ScoredCandidate:
        """Score a single candidate on novelty, feasibility, specificity."""
        try:
            response = await asyncio.wait_for(
                self._llm.chat(
                    messages=[
                        {"role": "system", "content": _SCORE_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": (
                                f"Original step: {original_step}\n\n"
                                f"Proposed revision: {candidate}\n\nScore:"
                            ),
                        },
                    ],
                    temperature=TEMPERATURE_BALANCED,
                    max_tokens=MAX_TOKENS_BRIEF,
                ),
                timeout=_SCORE_TIMEOUT,
            )
            raw = (response.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("\n```", 1)[0]
            data = json.loads(raw)
            return ScoredCandidate(
                description=candidate,
                novelty=int(data.get("novelty", 3)),
                feasibility=int(data.get("feasibility", 3)),
                specificity=int(data.get("specificity", 3)),
            )
        except Exception as exc:
            logger.debug("ToT scoring failed for candidate: %s", exc)
            return ScoredCandidate(description=candidate)

    async def best_candidate(
        self, step_description: str, failure_context: str,
    ) -> str:
        """Generate and score candidates, return the best one's description."""
        candidates = await self.generate_candidates(step_description, failure_context)
        scored = await asyncio.gather(
            *[self.score_candidate(c, step_description) for c in candidates],
            return_exceptions=True,
        )

        best: Optional[ScoredCandidate] = None
        for s in scored:
            if isinstance(s, ScoredCandidate):
                if best is None or s.aggregate > best.aggregate:
                    best = s

        if best is not None and best.aggregate >= 2.0:
            logger.info(
                "ToT: best candidate score %.2f (nov=%d, feas=%d, spec=%d)",
                best.aggregate, best.novelty, best.feasibility, best.specificity,
            )
            return best.description

        # Fallback: return the first candidate
        return candidates[0] if candidates else step_description
