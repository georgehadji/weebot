"""LayerDiagnosticAgent — classifies trajectory failures into one of 4 harness layers.

Trajectories are read from the TrajectoryRepo.  Each failed trajectory is
classified as one of:

- CONTRACT: Tool descriptions/schemas misled the agent
- SKILL: Retrieval missed relevant procedural knowledge
- ACTION: Action canonicalization failed (type coercion, missing args)
- TRAJECTORY: Trajectory regulation failed to detect a degenerate pattern
- REASONING: General LLM reasoning error (not harness-addressable)

This classification drives which layer editor is invoked during evolution.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from weebot.application.ports.llm_port import LLMPort

logger = logging.getLogger(__name__)


class FailureLayer(str, Enum):
    """Which harness layer should be updated to address this failure."""
    CONTRACT = "contract"
    SKILL = "skill"
    ACTION = "action"
    TRAJECTORY = "trajectory"
    REASONING = "reasoning"  # Not harness-addressable — flag for human review


_DIAGNOSTIC_SYSTEM = """You are a failure-diagnosis specialist for deterministic LLM agents.
Given a task description and a record of the agent's interaction (tools called,
errors encountered, final outcome), determine which layer of the runtime harness
should be updated.

Classification rules:
- CONTRACT: The agent misunderstood tool semantics, called wrong tool, or
  violated a protocol rule. Fix: update tool contract YAML.
- SKILL: The agent lacked procedural knowledge for a recurring sub-task.
  Fix: add or update a skill document.
- ACTION: The agent produced a syntactically invalid or non-executable action
  (wrong argument type, missing required arg). Fix: add canonicalization rule.
- TRAJECTORY: The agent repeated the same action, stagnated, or exhausted
  the budget without progress. Fix: adjust regulation thresholds.
- REASONING: The agent made an incorrect logical inference despite correct
  tool usage. Not harness-addressable — flag for human review.

Respond with ONE word: CONTRACT / SKILL / ACTION / TRAJECTORY / REASONING
Then on the next line, a one-sentence explanation."""


class LayerDiagnosticAgent:
    """Classify failed trajectories into harness layers."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def diagnose(
        self,
        task: str,
        trajectory_summary: str,
        model: Optional[str] = None,
    ) -> tuple[FailureLayer, str]:
        """Classify a single failed trajectory.

        Args:
            task: The original task description.
            trajectory_summary: Compact trace of tool calls, errors, outcomes.
            model: Optional model override.

        Returns:
            (FailureLayer, explanation) tuple.
        """
        response = await self._llm.chat(
            messages=[
                {"role": "system", "content": _DIAGNOSTIC_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Task: {task}\n\n"
                        f"Trajectory:\n{trajectory_summary[:2000]}\n\n"
                        "Diagnose the failure layer:"
                    ),
                },
            ],
            model=model,
            temperature=0.1,
            max_tokens=128,
        )

        content = (response.content or "").strip()
        first_line = content.split("\n")[0].strip().upper()
        explanation = content.split("\n")[1] if "\n" in content else content

        try:
            layer = FailureLayer(first_line)
        except ValueError:
            logger.warning(
                "Unrecognised diagnosis %r, defaulting to REASONING", first_line
            )
            layer = FailureLayer.REASONING

        return layer, explanation
