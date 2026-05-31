"""OptimizerAgent — frontier model that proposes skill edits.

This agent receives scored trajectories and the current skill document,
performs minibatch reflection over failures and successes, merges and
ranks proposals, and returns structured SkillEdit objects.

It is the implementation of OptimizerPort.  The optimizer model is
configured separately from the target model (stronger, higher reasoning
effort) and is never deployed with it.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from typing import Any

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.optimizer_port import OptimizerPort
from weebot.domain.models.skill import Skill
from weebot.domain.models.skill_edit import SkillEdit
from weebot.domain.models.trajectory import OptimizationBatch, TrajectorySummary
from weebot.application.skills.builtin.loader import load_optimizer_prompt

logger = logging.getLogger(__name__)


class OptimizerAgent(OptimizerPort):
    """Frontier-model-based optimizer for agent skills.

    The main responsibilities (paper §3.3–3.6) are:
    - Partitioning trajectories into minibatch reflection groups.
    - Calling the LLM with structured prompts to produce edits.
    - Merging and ranking those edits under a budget.
    - Producing epoch-boundary slow/meta updates.
    """

    def __init__(
        self,
        optimizer_llm: LLMPort,
        event_bus: EventBusPort | None = None,
    ):
        self._llm = optimizer_llm
        self._event_bus = event_bus

    # ── OptimizerPort implementation ─────────────────────────────────

    async def reflect_on_failures(
        self,
        batch: OptimizationBatch,
        current_skill: Skill,
        evolution_context: str = "",
    ) -> list[SkillEdit]:
        """Minibatch reflection over failure trajectories (paper §3.3)."""
        failures = [t for t in batch.trajectories if not t.passed]
        if not failures:
            return []

        # Cross-trajectory stats for the prompt
        all_modes = [m for t in failures for m in t.failure_modes]
        mode_counts = Counter(all_modes)
        common_failures = [m for m, c in mode_counts.most_common(5) if c >= 2]
        batch_stats = {
            "trajectory_count": len(failures),
            "success_rate": f"{batch.success_count}/{batch.success_count + batch.failure_count}",
            "common_failure_modes": common_failures,
        }

        minibatches = self._partition(failures, minibatch_size=8)
        system_prompt = load_optimizer_prompt("reflection_failure")

        results = await asyncio.gather(*[
            self._reflect_minibatch(
                system_prompt, mb, current_skill,
                batch_stats=batch_stats, evolution_context=evolution_context,
            )
            for mb in minibatches
        ])
        return self._flatten(results)

    async def reflect_on_successes(
        self,
        batch: OptimizationBatch,
        current_skill: Skill,
        evolution_context: str = "",
    ) -> list[SkillEdit]:
        """Minibatch reflection over success trajectories (paper §3.3)."""
        successes = [t for t in batch.trajectories if t.passed]
        if not successes:
            return []

        # Cross-trajectory stats for the prompt
        all_patterns = [p for t in successes for p in t.success_patterns]
        pattern_counts = Counter(all_patterns)
        common_patterns = [p for p, c in pattern_counts.most_common(5) if c >= 2]
        batch_stats = {
            "trajectory_count": len(successes),
            "success_rate": f"{batch.success_count}/{batch.success_count + batch.failure_count}",
            "common_success_patterns": common_patterns,
        }

        minibatches = self._partition(successes, minibatch_size=8)
        system_prompt = load_optimizer_prompt("reflection_success")

        results = await asyncio.gather(*[
            self._reflect_minibatch(
                system_prompt, mb, current_skill,
                batch_stats=batch_stats, evolution_context=evolution_context,
            )
            for mb in minibatches
        ])
        return self._flatten(results)

    async def merge_edits(
        self,
        failure_edits: list[SkillEdit],
        success_edits: list[SkillEdit],
    ) -> list[SkillEdit]:
        """Three-stage hierarchical merge (paper §3.3)."""
        merge_failures_prompt = load_optimizer_prompt("merge_failure")
        merge_successes_prompt = load_optimizer_prompt("merge_success")
        merge_final_prompt = load_optimizer_prompt("merge_final")

        # Stage 1: consolidate failure proposals
        merged_failures = await self._merge_group(
            merge_failures_prompt, failure_edits
        )

        # Stage 2: consolidate success proposals
        merged_successes = await self._merge_group(
            merge_successes_prompt, success_edits
        )

        # Stage 3: combine with failure priority
        return await self._merge_final(
            merge_final_prompt, merged_failures, merged_successes
        )

    async def rank_edits(
        self,
        edits: list[SkillEdit],
        budget: int,
        current_skill: Skill,
    ) -> list[SkillEdit]:
        """Rank edits by expected utility and clip to budget (paper §3.4)."""
        if not edits:
            return []

        prompt = load_optimizer_prompt("ranking")
        edits_json = [e.model_dump() for e in edits]

        response = await self._llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": prompt.replace(
                        "{budget}", str(budget)
                    ).replace(
                        "{skill_content}", current_skill.content[:2000]
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(edits_json, indent=2),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=2000,
        )

        try:
            data = json.loads(response.content)
            indices = data.get("selected_indices", [])[:budget]
            return [edits[i] for i in indices if i < len(edits)]
        except Exception as exc:
            logger.warning("Ranking LLM call failed: %s — falling back to support_count sort", exc)
            sorted_edits = sorted(edits, key=lambda e: e.support_count, reverse=True)
            return sorted_edits[:budget]

    async def plan_edits(
        self,
        batch: OptimizationBatch,
        current_skill: Skill,
        evolution_context: str = "",
    ) -> str:
        """Optional pre-reflect planning step (SIA-inspired).

        Returns a JSON string with root_causes, proposed_fixes, risks, and
        focus_sections, or empty string if the prompt file is absent or the
        LLM call fails.
        """
        try:
            prompt = load_optimizer_prompt("plan_edits")
        except FileNotFoundError:
            return ""

        user_content = (
            f"Skill (first 2000 chars):\n{current_skill.content[:2000]}\n\n"
            f"Batch: {batch.failure_count} failures, {batch.success_count} successes, "
            f"batch_score={batch.batch_score:.3f}"
        )
        if evolution_context:
            user_content += f"\n\nEvolution History:\n{evolution_context}"

        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=500,
            )
            json.loads(response.content)  # validate parseable
            return response.content
        except Exception as exc:
            logger.warning("plan_edits LLM call failed: %s — skipping planning step", exc)
            return ""

    async def slow_update(
        self,
        prev_skill: Skill,
        curr_skill: Skill,
        longitudinal_data: list[tuple],
    ) -> str:
        """Epoch-boundary slow update (paper §3.6)."""
        prompt = load_optimizer_prompt("slow_update")
        return await self._produce_guidance(
            prompt,
            prev_skill, curr_skill, longitudinal_data,
        )

    async def meta_skill(
        self,
        prev_skill: Skill,
        curr_skill: Skill,
        longitudinal_data: list[tuple],
    ) -> str:
        """Optimizer-side meta coaching (paper §3.6)."""
        prompt = load_optimizer_prompt("meta_skill")
        return await self._produce_guidance(
            prompt,
            prev_skill, curr_skill, longitudinal_data,
        )

    # ── internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _partition(
        items: list[TrajectorySummary],
        minibatch_size: int,
    ) -> list[list[TrajectorySummary]]:
        """Split items into minibatches."""
        return [items[i:i + minibatch_size] for i in range(0, len(items), minibatch_size)]

    async def _reflect_minibatch(
        self,
        system_prompt: str,
        minibatch: list[TrajectorySummary],
        skill: Skill,
        batch_stats: dict | None = None,
        evolution_context: str = "",
    ) -> list[SkillEdit]:
        """Run one analyst worker over a minibatch of trajectories."""
        trajectories_json = json.dumps(
            [t.model_dump() for t in minibatch], indent=2
        )
        user_content = f"Current skill:\n{skill.content}\n\nTrajectories:\n{trajectories_json}"
        if batch_stats:
            user_content += f"\n\nBatch Statistics:\n{json.dumps(batch_stats, indent=2)}"
        if evolution_context:
            user_content += f"\n\nEvolution History:\n{evolution_context}"

        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=3000,
            )
            return self._parse_edits(response.content)
        except Exception as exc:
            logger.warning("Minibatch reflection failed: %s", exc)
            return []

    @staticmethod
    def _parse_edits(raw: str) -> list[SkillEdit]:
        """Parse a JSON response into SkillEdit objects."""
        try:
            data = json.loads(raw)
            edits_data = data.get("edits", [])
            return [
                SkillEdit(
                    op=e["op"],
                    target=e.get("target"),
                    content=e.get("content", ""),
                    support_count=e.get("support_count", 1),
                    source_type=e.get("source_type", "failure"),
                )
                for e in edits_data
            ]
        except Exception as exc:
            logger.warning("Failed to parse edits from LLM response: %s", exc)
            return []

    async def _merge_group(
        self,
        system_prompt: str,
        edits: list[SkillEdit],
    ) -> list[SkillEdit]:
        """Merge a group of edits (Stage 1 or 2)."""
        if not edits:
            return []
        edits_json = json.dumps([e.model_dump() for e in edits], indent=2)
        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": edits_json},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=2000,
            )
            return self._parse_edits(response.content)
        except Exception as exc:
            logger.warning("Merge step failed: %s — using all edits", exc)
            return edits

    async def _merge_final(
        self,
        system_prompt: str,
        failure_edits: list[SkillEdit],
        success_edits: list[SkillEdit],
    ) -> list[SkillEdit]:
        """Final merge with failure priority."""
        payload = json.dumps(
            {"failure_edits": [e.model_dump() for e in failure_edits],
             "success_edits": [e.model_dump() for e in success_edits]},
            indent=2,
        )
        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": payload},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=2000,
            )
            return self._parse_edits(response.content)
        except Exception as exc:
            logger.warning("Final merge failed: %s", exc)
            return failure_edits + success_edits

    async def _produce_guidance(
        self,
        system_prompt: str,
        prev_skill: Skill,
        curr_skill: Skill,
        longitudinal_data: list[tuple],
    ) -> str:
        """Produce slow/meta guidance from longitudinal comparison."""
        comparisons = []
        for prev_traj, curr_traj in longitudinal_data:
            comparisons.append({
                "task_id": prev_traj.task_id,
                "previous_score": prev_traj.score,
                "current_score": curr_traj.score,
            })

        user_content = (
            f"Previous skill:\n{prev_skill.content[:2000]}\n\n"
            f"Current skill:\n{curr_skill.content[:2000]}\n\n"
            f"Longitudinal comparison:\n{json.dumps(comparisons, indent=2)}"
        )
        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=2000,
            )
            data = json.loads(response.content)
            field = data.get("slow_update_content") or data.get("meta_skill_content") or data.get("content", "")
            return str(field)
        except Exception as exc:
            logger.warning("Guidance generation failed: %s", exc)
            return ""

    @staticmethod
    def _flatten(nested: list[list[SkillEdit]]) -> list[SkillEdit]:
        """Flatten a list of edit lists into a single list."""
        result = []
        for sublist in nested:
            result.extend(sublist)
        return result
