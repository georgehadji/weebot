"""OptimizerPort — abstract interface for the skill optimizer.

The optimizer is a separate frontier model that analyses scored trajectories
and proposes structured edits to a skill document.  It NEVER runs the target
model — it only sees TrajectorySummary objects and the current skill.

This port wraps the five core operations from the SkillOpt paper:
  1. reflect_on_failures  — minibatch reflection over failed trajectories
  2. reflect_on_successes — minibatch reflection over successful trajectories
  3. merge_edits          — hierarchical merge (failure priority, dedup, conflict resolution)
  4. rank_edits           — rank by expected utility, clip to budget L_t
  5. slow_update          — epoch-boundary longitudinal comparison
  6. meta_skill           — optimizer-side coaching (not deployed)
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.domain.models.skill import Skill
from weebot.domain.models.skill_edit import SkillEdit
from weebot.domain.models.trajectory import OptimizationBatch


class OptimizerPort(ABC):
    """Abstract interface for the skill optimizer."""

    @abstractmethod
    async def reflect_on_failures(
        self,
        batch: OptimizationBatch,
        current_skill: Skill,
    ) -> list[SkillEdit]:
        """Analyse failure trajectories and propose corrective edits."""
        ...

    @abstractmethod
    async def reflect_on_successes(
        self,
        batch: OptimizationBatch,
        current_skill: Skill,
    ) -> list[SkillEdit]:
        """Analyse success trajectories and propose reinforcing edits."""
        ...

    @abstractmethod
    async def merge_edits(
        self,
        failure_edits: list[SkillEdit],
        success_edits: list[SkillEdit],
    ) -> list[SkillEdit]:
        """Hierarchically merge failure and success proposals.

        Failure edits take priority.  Duplicates and contradictions
        are resolved.  Returns a merged pool for ranking.
        """
        ...

    @abstractmethod
    async def rank_edits(
        self,
        edits: list[SkillEdit],
        budget: int,
        current_skill: Skill,
    ) -> list[SkillEdit]:
        """Rank edits by expected utility and clip to *budget*.

        Ranking criteria (in order, from the paper):
          1. Systematic impact — widespread recurring failures first
          2. Complementarity — fill gaps, don't duplicate
          3. Generality — general principles over specific examples
          4. Actionability — clear concrete guidance over vague advice
        """
        ...

    @abstractmethod
    async def slow_update(
        self,
        prev_skill: Skill,
        curr_skill: Skill,
        longitudinal_data: list[tuple],
    ) -> str:
        """Produce epoch-boundary guidance for the protected SLOW_UPDATE section.

        Args:
            prev_skill: The skill at the end of the previous epoch.
            curr_skill: The skill at the end of the current epoch.
            longitudinal_data: Adjacent-epoch comparison of the same tasks.

        Returns:
            Guidance text to write into the protected section.
        """
        ...

    @abstractmethod
    async def meta_skill(
        self,
        prev_skill: Skill,
        curr_skill: Skill,
        longitudinal_data: list[tuple],
    ) -> str:
        """Produce optimizer-side coaching (not deployed with target model).

        Returns:
            Compact optimizer guidance for future edit calls.
        """
        ...

    async def plan_edits(
        self,
        batch: OptimizationBatch,
        current_skill: Skill,
        evolution_context: str = "",
    ) -> str:
        """Optional pre-reflect planning step (SIA-inspired).

        Produces a structured JSON improvement plan before the reflect calls
        so the optimizer reasons about root causes before proposing edits.

        Returns:
            JSON string with keys root_causes, proposed_fixes, risks,
            focus_sections — or empty string (no-op default).

        Concrete optimizers may override this to enable the planning step.
        """
        return ""
