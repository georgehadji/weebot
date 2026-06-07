"""GoalAgent — decomposes a high-level prompt into a SwarmSpec.

Single LLM call using structured output (Pydantic).  The agent reads
the prompt, determines what sub-goals are needed, auto-generates role
names and tool assignments, and returns a SwarmSpec ready for parallel
execution via dispatch_parallel_tasks.

Model: MODEL_CASCADE_TIER1 (Owl Alpha — free, agentic, tool-aware).
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.swarm import SwarmSpec, SubGoal

logger = logging.getLogger(__name__)

_GOAL_SYSTEM_PROMPT = """You are a task decomposition specialist. Given a user's research
or analysis prompt, break it into 3-8 independent sub-goals that can run
in parallel.

For each sub-goal, assign:
- description: what this sub-agent should investigate (one clear sentence)
- role: a short role name (snake_case, e.g. "pricing_analyst")
- tools: 1-3 tool names from: web_search, advanced_browser, python_execute,
  file_editor, knowledge, design_system, browser_inspector
- priority: 0 (urgent), 1 (normal), or 2 (nice-to-have)

Rules:
- Every sub-goal must be INDEPENDENT — no sub-goal should depend on
  another sub-goal's output.
- Prefer web_search over advanced_browser for simple lookups.
- Assign python_execute only when data processing is needed.
- 3-5 sub-goals is the sweet spot.  More than 8 is rarely justified.

Return ONLY a JSON object with this schema:
{
  "goals": [
    {"description": "...", "role": "...", "tools": [...], "priority": 0}
  ],
  "max_concurrency": 4,
  "synthesis_strategy": "cluster"
}"""


class GoalAgent:
    """Decompose a high-level prompt into a SwarmSpec via one LLM call."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def decompose(
        self, prompt: str, max_goals: int = 8, model: Optional[str] = None
    ) -> SwarmSpec:
        """Return a SwarmSpec with auto-generated roles and tool assignments.

        Args:
            prompt: The user's research/analysis prompt.
            max_goals: Upper bound on sub-goals (clamped in parsing).
            model: Optional model override.

        Returns:
            SwarmSpec ready for parallel execution.

        Raises:
            ValueError: If the LLM response cannot be parsed.
        """
        response = await self._llm.chat(
            messages=[
                {"role": "system", "content": _GOAL_SYSTEM_PROMPT},
                {"role": "user", "content": f"Decompose this task:\n\n{prompt}"},
            ],
            model=model,
            temperature=TEMPERATURE_DEFAULT,
            max_tokens=2048,
        )

        content = response.content or ""
        try:
            data = self._parse_json(content)
        except json.JSONDecodeError:
            logger.warning("GoalAgent: unparseable response, using fallback")
            return self._fallback_spec(prompt)

        goals = []
        for g in data.get("goals", [])[:max_goals]:
            goals.append(
                SubGoal(
                    description=str(g.get("description", "")),
                    role=str(g.get("role", "researcher")),
                    tools=[str(t) for t in g.get("tools", ["web_search"])],
                    priority=int(g.get("priority", 0)),
                )
            )

        if not goals:
            return self._fallback_spec(prompt)

        return SwarmSpec(
            original_prompt=prompt,
            goals=goals,
            max_concurrency=int(data.get("max_concurrency", 4)),
            synthesis_strategy=str(data.get("synthesis_strategy", "cluster")),
        )

    @staticmethod
    def _parse_json(content: str) -> dict:
        """Extract JSON object from potentially noisy LLM output."""
        content = content.strip()
        # Try direct parse first
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        # Extract from markdown code block
        if "```" in content:
            start = content.find("{")
            end = content.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(content[start:end])
        raise json.JSONDecodeError("No JSON found", content, 0)

    @staticmethod
    def _fallback_spec(prompt: str) -> SwarmSpec:
        """Minimal fallback when LLM decomposition fails."""
        return SwarmSpec(
            original_prompt=prompt,
            goals=[
                SubGoal(
                    description=prompt[:200],
                    role="researcher",
                    tools=["web_search"],
                    priority=0,
                )
            ],
            max_concurrency=1,
            synthesis_strategy="merge",
        )
