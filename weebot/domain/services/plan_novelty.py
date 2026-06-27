"""PlanNoveltyTracker — diversity-driven re-planning (HyperAgents Enhancement 3).

Matching DGM-H's novelty bonus for parent selection: agents with fewer
descendants get higher selection weight.  Applied here to plan diversity:
when the planner re-generates similar steps after failures, the
PlanNoveltyTracker injects an avoidance prompt listing approaches that
have been tried 3+ times without success.

This prevents the step-repetition loop that currently plagues the executor
when it retries the same failed approach.
"""
from __future__ import annotations

from collections import Counter
from typing import List, Optional

from weebot.domain.models.plan import Plan, Step


class PlanNoveltyTracker:
    """Tracks plan diversity and generates avoidance prompts for re-planning."""

    _MIN_FREQUENCY_FOR_AVOIDANCE: int = 3

    def diversity_score(self, plans: list[Plan]) -> float:
        """Compute how diverse a sequence of plans is.

        0.0 = all plans have identical step descriptions.
        1.0 = every step description across all plans is unique.

        Args:
            plans: A sequence of plans (typically from PlanHistory).

        Returns:
            Diversity score in [0.0, 1.0].
        """
        if len(plans) < 2:
            return 1.0  # Single plan is maximally diverse by definition

        all_descriptions: list[str] = []
        for plan in plans:
            for step in plan.steps:
                all_descriptions.append(step.description.lower().strip())

        if not all_descriptions:
            return 1.0

        unique = len(set(all_descriptions))
        return unique / len(all_descriptions)

    def frequent_approaches(
        self,
        plans: list[Plan],
        min_count: int | None = None,
    ) -> list[str]:
        """Return step descriptions that appear frequently across plans.

        Args:
            plans: Sequence of plans to analyze.
            min_count: Minimum occurrences to flag (default: 3).

        Returns:
            List of step descriptions that appear >= min_count times,
            ordered by frequency (most frequent first).
        """
        if min_count is None:
            min_count = self._MIN_FREQUENCY_FOR_AVOIDANCE

        counter: Counter[str] = Counter()
        for plan in plans:
            for step in plan.steps:
                counter[step.description.lower().strip()] += 1

        return [
            desc for desc, count in counter.most_common()
            if count >= min_count
        ]

    def avoidance_prompt(
        self,
        plans: list[Plan],
        min_count: int | None = None,
    ) -> str:
        """Generate a prompt fragment listing approaches to avoid.

        Args:
            plans: Plan history to analyze.
            min_count: Minimum occurrences to flag (default: 3).

        Returns:
            A prompt string for injection into the planner, or empty
            string if no approaches need avoiding.
        """
        frequent = self.frequent_approaches(plans, min_count=min_count)
        if not frequent:
            return ""

        lines = [
            "\n\n## Approaches to AVOID (tried multiple times without success):"
        ]
        for desc in frequent[:5]:  # Cap at 5 to avoid prompt bloat
            lines.append(f"- {desc}")
        lines.append(
            "\nIMPORTANT: Do NOT use any of the above approaches. "
            "Propose a fundamentally DIFFERENT strategy."
        )
        return "\n".join(lines)
