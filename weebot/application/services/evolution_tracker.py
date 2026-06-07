"""EvolutionTracker — records LLM-generated epoch narratives in Skill.evolution_log.

After each SkillOptFlow epoch, call record_epoch() to generate a 2-4 sentence
narrative summarising what changed and why, then append it to the skill's
evolution_log. The log feeds back into the optimizer's reflection prompts so
it can avoid repeating failed approaches across epochs (SIA ContextManager pattern).
"""
from __future__ import annotations

import json
import logging

from weebot.application.ports.llm_port import LLMPort
from weebot.application.skills.builtin.loader import load_optimizer_prompt
from weebot.domain.models.event import EpochCompleted
from weebot.domain.models.skill import EvolutionEntry, Skill

logger = logging.getLogger(__name__)


class EvolutionTracker:
    """Generates and appends epoch narratives to Skill.evolution_log."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def record_epoch(
        self,
        skill: Skill,
        prev_skill: Skill,
        epoch_event: EpochCompleted,
    ) -> Skill:
        """Generate a narrative for the completed epoch and return the updated Skill.

        Args:
            skill: The skill at the END of the epoch (post slow-update).
            prev_skill: The skill at the START of the epoch.
            epoch_event: The EpochCompleted event emitted by SkillOptFlow.

        Returns:
            A new Skill with the epoch's EvolutionEntry appended to evolution_log.
        """
        narrative = await self._generate_narrative(skill, prev_skill, epoch_event)
        prev_best = prev_skill.best.validation_score or 0.0

        entry = EvolutionEntry(
            epoch=epoch_event.epoch,
            narrative=narrative,
            accepted_count=epoch_event.edits_accepted,
            rejected_count=epoch_event.edits_rejected,
            best_score=epoch_event.best_validation_score,
            score_delta=epoch_event.best_validation_score - prev_best,
            slow_update_applied=epoch_event.slow_update_applied,
        )
        return skill.add_evolution_entry(entry)

    async def _generate_narrative(
        self,
        skill: Skill,
        prev_skill: Skill,
        epoch_event: EpochCompleted,
    ) -> str:
        """Call the LLM with epoch stats + diff summary, return narrative string."""
        try:
            prompt = load_optimizer_prompt("evolution_context")
        except FileNotFoundError:
            return self._fallback_narrative(epoch_event)

        # Lightweight diff: line set difference — no external deps
        prev_lines = set(prev_skill.content.splitlines())
        curr_lines = set(skill.content.splitlines())
        added = sorted(curr_lines - prev_lines)[:10]
        removed = sorted(prev_lines - curr_lines)[:10]

        prior_narratives = [e.narrative for e in skill.evolution_log[-3:]]

        user_msg = json.dumps(
            {
                "epoch": epoch_event.epoch,
                "accepted": epoch_event.edits_accepted,
                "rejected": epoch_event.edits_rejected,
                "best_score": epoch_event.best_validation_score,
                "slow_update_applied": epoch_event.slow_update_applied,
                "lines_added_sample": added,
                "lines_removed_sample": removed,
                "prior_narratives": prior_narratives,
            },
            indent=2,
        )

        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=TEMPERATURE_BALANCED,
                max_tokens=300,
            )
            data = json.loads(response.content)
            narrative = data.get("narrative", "")
            if narrative:
                return narrative
        except Exception as exc:
            logger.warning("EvolutionTracker LLM call failed: %s — using fallback", exc)

        return self._fallback_narrative(epoch_event)

    @staticmethod
    def _fallback_narrative(epoch_event: EpochCompleted) -> str:
        """Produce a deterministic narrative without LLM when generation fails."""
        return (
            f"Epoch {epoch_event.epoch}: accepted {epoch_event.edits_accepted} edits, "
            f"rejected {epoch_event.edits_rejected}. "
            f"Best validation score: {epoch_event.best_validation_score:.3f}. "
            f"Slow update applied: {epoch_event.slow_update_applied}."
        )
