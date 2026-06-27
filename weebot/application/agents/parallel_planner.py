"""Parallel planner — generates multiple plan candidates per subtask concurrently (DPPM).

Based on the paper "Fundamentals of Building Autonomous LLM Agents"
(arXiv:2510.09244v1), §4.4 — DPPM (Decompose, Plan in Parallel, and Merge):

1. Decompose the main task into subtasks
2. For each subtask, generate multiple planning options concurrently
3. Merge the best options into a coherent global plan

This module produces ``PlanCandidate`` objects.  The companion module
``plan_merger.py`` merges them into a final ``Plan``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Optional

from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.plan import Plan, Step, StepStatus, PlanStatus

logger = logging.getLogger(__name__)

# ── Data model ───────────────────────────────────────────────────────────

class SubtaskDefinition:
    """A single subtask with multiple planning alternatives."""
    def __init__(
        self,
        title: str,
        description: str,
        candidates: list[list[dict[str, str]]] | None = None,
    ) -> None:
        self.title = title
        self.description = description
        # candidates: each is a list of {"action": "...", "tool": "..."} dicts
        self.candidates = candidates or []

    def __repr__(self) -> str:
        return f"Subtask({self.title!r}, {len(self.candidates)} candidates)"


class PlanCandidate:
    """A single complete plan produced by DPPM."""
    def __init__(
        self,
        title: str,
        steps: list[Step],
        score: float = 0.0,
        source_subtasks: Optional[list[str]] = None,
    ) -> None:
        self.title = title
        self.steps = steps
        self.score = score
        self.source_subtasks = source_subtasks or []

    def to_plan(self) -> Plan:
        return Plan(
            title=self.title,
            steps=self.steps,
            status=PlanStatus.CREATED,
        )

    def __repr__(self) -> str:
        return f"PlanCandidate({self.title!r}, {len(self.steps)} steps, score={self.score:.2f})"


# ── Parallel planner ─────────────────────────────────────────────────────

class ParallelPlanner:
    """Generates multiple plan candidates by decomposing and planning in parallel.

    Usage:
        planner = ParallelPlanner(llm=llm_port)
        candidates = await planner.generate(prompt="fix login bug")
        # candidates[0].steps -> list of Step objects
    """

    # A task is "complex" if its description exceeds this many chars
    # (heuristic for when DPPM is worth the extra LLM calls)
    COMPLEXITY_THRESHOLD: int = 200

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def generate(
        self,
        prompt: str,
        num_alternatives: int = 2,
    ) -> list[PlanCandidate]:
        """Generate multiple plan candidates using DPPM.

        Args:
            prompt: The user's task description.
            num_alternatives: Number of alternative plans to generate per subtask.

        Returns:
            List of PlanCandidate, sorted by score descending.
        """
        # Step 1: Decompose into subtasks
        subtasks = await self._decompose(prompt)
        if not subtasks:
            return []

        # Step 2: For each subtask, generate alternatives concurrently
        for subtask in subtasks:
            candidates = await asyncio.gather(*[
                self._plan_subtask(subtask, i + 1)
                for i in range(num_alternatives)
            ])
            subtask.candidates = [c for c in candidates if c is not None]

        # Step 3: Merge into complete candidates
        candidates = self._assemble_candidates(subtasks, prompt)
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    async def _decompose(self, prompt: str) -> list[SubtaskDefinition]:
        """LLM call: break a task into subtasks."""
        sys_prompt = (
            "You are a task decomposition expert. Break the following task into "
            "3-6 subtasks. Each subtask must have a title and a one-sentence description.\n\n"
            f"Task: {prompt}\n\n"
            "Respond with JSON: {\"subtasks\": ["
            "{\"title\": \"short title\", \"description\": \"what to do\"}, ..."
            "]}\n"
            "Rules:\n"
            "- At most 6 subtasks.\n"
            "- Each subtask should be independently executable.\n"
            "- Order by logical dependency."
        )
        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": sys_prompt}],
                max_tokens=1000,
            )
            text = response.content.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
            data = json.loads(text)
            subtasks_data = data.get("subtasks", [])
            return [
                SubtaskDefinition(title=s.get("title", ""), description=s.get("description", ""))
                for s in subtasks_data if s.get("title") and s.get("description")
            ]
        except Exception as exc:
            logger.warning("DPPM decomposition failed: %s", exc)
            return []

    async def _plan_subtask(
        self,
        subtask: SubtaskDefinition,
        alternative_index: int,
    ) -> Optional[list[dict[str, str]]]:
        """LLM call: generate one alternative plan for a subtask."""
        sys_prompt = (
            "You are a planning expert. Given a subtask, generate a sequence of "
            f"2-5 concrete actions to complete it (alternative #{alternative_index}).\n\n"
            f"Subtask: {subtask.title}: {subtask.description}\n\n"
            "Respond with JSON: {\"steps\": ["
            "{\"action\": \"do something\", \"tool\": \"tool_name\"}, ..."
            "]}\n"
            "Rules:\n"
            "- Each action is 3-15 words.\n"
            "- 'tool' is the weebot tool name: bash, python_execute, file_editor, "
            "web_search, advanced_browser, image_gen, etc.\n"
            "- At most 5 steps per subtask.\n"
            "- Be specific about what each action achieves."
        )
        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": sys_prompt}],
                max_tokens=800,
            )
            text = response.content.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
            data = json.loads(text)
            return data.get("steps", [])
        except Exception as exc:
            logger.warning("DPPM subtask planning failed for %s: %s", subtask.title, exc)
            return None

    def _assemble_candidates(
        self,
        subtasks: list[SubtaskDefinition],
        prompt: str,
    ) -> list[PlanCandidate]:
        """Combine subtask alternatives into complete plan candidates.

        Uses a greedy strategy: for each subtask position, try the best-ranked
        alternative first, skipping any that are clearly incompatible.
        """
        candidates = []

        # Simple greedy: take the first alternative for each subtask as one candidate,
        # the second as another, etc.
        max_alternatives = max(len(s.candidates) for s in subtasks) if subtasks else 0
        for alt_idx in range(max_alternatives):
            steps: list[Step] = []
            step_id = 0
            sources: list[str] = []

            for subtask in subtasks:
                if alt_idx < len(subtask.candidates):
                    alt = subtask.candidates[alt_idx]
                else:
                    alt = subtask.candidates[-1]  # clamp to last available

                sources.append(subtask.title)
                for action in alt:
                    step_id += 1
                    desc = action.get("action", "")
                    tool = action.get("tool", "")
                    if tool:
                        desc = f"[{tool}] {desc}"
                    steps.append(Step(
                        id=f"dppm-{step_id}",
                        description=desc,
                        status=StepStatus.PENDING,
                    ))

            candidates.append(PlanCandidate(
                title=f"DPPM plan (variant {alt_idx + 1})",
                steps=steps,
                score=0.9 - (alt_idx * 0.1),  # Score decreases for later variants
                source_subtasks=sources,
            ))

        if not candidates:
            # Fallback: one-step placeholder
            candidates.append(PlanCandidate(
                title=prompt[:80],
                steps=[Step(
                    id="dppm-1",
                    description=prompt[:200],
                    status=StepStatus.PENDING,
                )],
                score=0.5,
            ))

        return candidates

    @classmethod
    def is_complex_task(cls, prompt: str) -> bool:
        """Heuristic: is this task complex enough to warrant DPPM?"""
        return len(prompt) > cls.COMPLEXITY_THRESHOLD
