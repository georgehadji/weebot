"""ComparisonRunner — A/B evaluation: same prompt with and without a skill.

Runs the same prompt through PlanActFlow twice:
- Run A: skill context loaded
- Run B: skill context omitted

Compares outputs using TaskScorer and reports quality delta.
Useful for measuring whether a skill actually improves agent output.

Inspired by revfactory/harness Phase 6-3 with-skill vs without-skill testing.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from weebot.domain.models.session import Session
from weebot.application.harness.scorer import TaskScorer

logger = logging.getLogger(__name__)


@dataclass
class ComparisonResult:
    """Result of a single with-vs-without comparison."""
    run_with: str = ""        # Agent output WITH the skill
    run_without: str = ""     # Agent output WITHOUT the skill
    score_with: float = 0.0
    score_without: float = 0.0
    delta: float = 0.0        # score_with - score_without
    passed: bool = False      # True if delta > 0 or both >= same

    @property
    def improvement(self) -> str:
        """Human-readable improvement indicator."""
        if self.delta > 0.1:
            return "significant"
        if self.delta > 0.05:
            return "moderate"
        if self.delta > 0.0:
            return "slight"
        if self.delta == 0.0:
            return "neutral"
        return "regression"


@dataclass
class ComparisonReport:
    """Full report across all test prompts."""
    skill_name: str
    results: list[ComparisonResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def avg_delta(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.delta for r in self.results) / len(self.results)

    @property
    def avg_score_with(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.score_with for r in self.results) / len(self.results)

    @property
    def avg_score_without(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.score_without for r in self.results) / len(self.results)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.passed)


class ComparisonRunner:
    """Runs with-vs-without A/B evaluation for a skill.

    Args:
        flow_factory: Callable that creates a PlanActFlow from a Session.
            Must accept ``skill_names`` kwarg: when provided, loads those
            skills into context; when empty, runs without skill context.
    """

    def __init__(
        self,
        flow_factory: Callable[..., Any],
    ) -> None:
        self._flow_factory = flow_factory
        self._scorer = TaskScorer()

    async def evaluate(
        self,
        skill_name: str,
        test_prompts: list[str],
        expected: Optional[list[str]] = None,
    ) -> ComparisonReport:
        """Run A/B comparison across test prompts.

        Args:
            skill_name: Name of the skill to test.
            test_prompts: List of prompts to run in both modes.
            expected: Optional list of expected answers for scoring.

        Returns:
            ``ComparisonReport`` with per-prompt results.
        """
        report = ComparisonReport(skill_name=skill_name)

        for i, prompt in enumerate(test_prompts):
            try:
                result = await self._compare_single(
                    skill_name=skill_name,
                    prompt=prompt,
                    expected=expected[i] if expected else None,
                )
                report.results.append(result)
            except Exception as exc:
                logger.warning("Comparison failed for prompt %d: %s", i, exc)
                report.errors.append(f"Prompt {i}: {exc}")

        return report

    async def _compare_single(
        self,
        skill_name: str,
        prompt: str,
        expected: Optional[str] = None,
    ) -> ComparisonResult:
        """Run one prompt with and without the skill, then compare."""
        # Run WITH skill
        output_with = await self._run_with_skill(skill_name, prompt)
        score_with = await self._score_output(output_with, expected)

        # Run WITHOUT skill
        output_without = await self._run_without_skill(prompt)
        score_without = await self._score_output(output_without, expected)

        return ComparisonResult(
            run_with=output_with[:500],
            run_without=output_without[:500],
            score_with=score_with,
            score_without=score_without,
            delta=score_with - score_without,
            passed=score_with >= score_without,
        )

    async def _run_with_skill(self, skill_name: str, prompt: str) -> str:
        """Run the prompt with the skill loaded."""
        import uuid
        session = Session(
            id=f"ab-with-{uuid.uuid4().hex[:8]}",
            user_id="ab-eval",
            agent_id="ab-agent",
        )
        flow = self._flow_factory(
            session=session,
            skill_names=[skill_name],
        )
        return await self._collect_output(flow, prompt)

    async def _run_without_skill(self, prompt: str) -> str:
        """Run the prompt without any skill loaded."""
        import uuid
        session = Session(
            id=f"ab-without-{uuid.uuid4().hex[:8]}",
            user_id="ab-eval",
            agent_id="ab-agent",
        )
        flow = self._flow_factory(
            session=session,
            skill_names=[],
        )
        return await self._collect_output(flow, prompt)

    async def _collect_output(self, flow: Any, prompt: str) -> str:
        """Run *flow* with *prompt* and return the response text."""
        response_text = ""
        async for event in flow.run(prompt):
            if getattr(event, "type", "") == "message":
                response_text = getattr(event, "message", "") or response_text
        return response_text

    async def _score_output(self, output: str, expected: Optional[str]) -> float:
        """Score *output* against *expected* using TaskScorer."""
        if expected is None:
            # Without expected answer, score by output length heuristic
            return min(1.0, len(output) / 1000) if output else 0.0
        return self._scorer._token_overlap(expected, output)
