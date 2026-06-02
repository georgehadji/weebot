"""LayerEditorAgent — proposes harness edits based on trajectory failure diagnosis.

Given a FailedLayer classification and evidence from the failed trajectory,
generates a structured HarnessEdit proposal.  Edits target one of:
- Tool contract YAML (contract layer)
- Skill markdown (skill layer)
- Canonicalization rules (action layer)
- Trajectory thresholds (trajectory layer)

Each edit is validated against regression tasks before acceptance.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from weebot.application.agents.layer_diagnostics_agent import FailureLayer
from weebot.application.ports.llm_port import LLMPort

logger = logging.getLogger(__name__)


class HarnessEdit:
    """A single proposed edit to the harness."""

    def __init__(
        self,
        layer: FailureLayer,
        target: str,
        change: str,
        evidence: str,
    ):
        self.layer = layer
        self.target = target
        self.change = change
        self.evidence = evidence


_EDITOR_SYSTEM = """You are a harness engineer for deterministic LLM agents. Given a
failure diagnosis and the current harness state, propose a minimal edit to prevent
the failure from recurring.

Edit types by layer:
- CONTRACT → propose a YAML change to a tool contract (pitfalls, coercions, defaults)
- SKILL → propose a new skill document or edit to an existing one
- ACTION → propose a new canonicalization rule (type coercion, block pattern, default)
- TRAJECTORY → propose threshold changes (repetition, stagnation, budget)

Return a JSON object with:
{
  "target": "file path or config key",
  "change": "description of the exact change",
  "rationale": "why this fixes the failure",
  "estimated_impact": "low/medium/high"
}

Be specific. For CONTRACT edits, specify the exact YAML path and value.
For ACTION edits, specify the exact coercion rule."""


class LayerEditorAgent:
    """Proposes harness edits from trajectory failure evidence."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def propose_edit(
        self,
        layer: FailureLayer,
        task: str,
        trajectory_summary: str,
        current_harness_summary: str = "",
        model: Optional[str] = None,
    ) -> Optional[HarnessEdit]:
        """Generate a harness edit for a diagnosed failure.

        Args:
            layer: Which harness layer to edit.
            task: Original task description.
            trajectory_summary: The failed trajectory trace.
            current_harness_summary: Current harness config (optional).
            model: Optional model override.

        Returns:
            HarnessEdit or None if the diagnosis is REASONING.
        """
        if layer == FailureLayer.REASONING:
            logger.info("REASONING failure — not harness-addressable, skipping edit")
            return None

        response = await self._llm.chat(
            messages=[
                {"role": "system", "content": _EDITOR_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Layer: {layer.value}\n"
                        f"Task: {task}\n\n"
                        f"Trajectory:\n{trajectory_summary[:2000]}\n\n"
                        f"Current harness:\n{current_harness_summary or '(default)'}\n\n"
                        "Propose an edit:"
                    ),
                },
            ],
            model=model,
            temperature=0.2,
            max_tokens=512,
        )

        try:
            data = self._parse_json(response.content or "")
            target = data.get("target", "")
            change = data.get("change", "")
            rationale = data.get("rationale", "")
            return HarnessEdit(
                layer=layer,
                target=target,
                change=change,
                evidence=f"{rationale} | {trajectory_summary[:300]}",
            )
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("Failed to parse harness edit proposal: %s", exc)
            return None

    @staticmethod
    def _parse_json(content: str) -> dict:
        content = content.strip()
        if content.startswith("```"):
            start = content.find("{")
            end = content.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(content[start:end])
        return json.loads(content)
