"""DebateTool — multi-perspective analysis with reconciliation (Phase 3).

Spawns 3 perspective agents (optimist, pessimist, pragmatist) via
dispatch_parallel_tasks.  Each researches the question independently
using their assigned framing.  A reconciler agent identifies consensus,
dissent, and blind spots, producing a balanced DebateResult.

Reuses Phase 1 swarm infrastructure (dispatch + synthesize pattern).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from weebot.tools.base import BaseTool, ToolResult
from weebot.domain.models.debate import DebateResult, Viewpoint

logger = logging.getLogger(__name__)

_PERSPECTIVES = [
    {
        "role": "optimist",
        "framing": (
            "You are an OPTIMIST. Focus on the upside, opportunities, best-case "
            "scenarios, and reasons this will succeed. Highlight strengths, "
            "positive trends, and favorable evidence."
        ),
    },
    {
        "role": "pessimist",
        "framing": (
            "You are a PESSIMIST. Focus on risks, downsides, worst-case scenarios, "
            "and reasons this could fail. Highlight weaknesses, threats, and "
            "countervailing evidence. Be the devil's advocate."
        ),
    },
    {
        "role": "pragmatist",
        "framing": (
            "You are a PRAGMATIST. Focus on what's actually likely to happen, "
            "balancing optimism and pessimism. Highlight trade-offs, practical "
            "constraints, and evidence-backed middle-ground positions."
        ),
    },
]

_RECONCILER_SYSTEM = """You are a debate reconciler. Three analysts with different
perspectives (optimist, pessimist, pragmatist) have researched the same question
independently. Your job:

1. Identify CONSENSUS — what do all three agree on?
2. Identify DISSENT — where do they disagree, and what does each say?
3. Identify BLIND SPOTS — what important angle did nobody cover?
4. Produce a SYNTHESIS — a balanced 3-5 paragraph analysis that integrates
   all viewpoints fairly, giving appropriate weight to evidence.

Return ONLY a JSON object:
{
  "consensus": ["point 1", "point 2"],
  "dissent": [{"topic": "...", "optimist": "...", "pessimist": "...", "pragmatist": "..."}],
  "blind_spots": ["uncovered angle"],
  "synthesis": "3-5 paragraph balanced analysis...",
  "confidence": 0.85
}"""


class DebateTool(BaseTool):
    """Analyze a question from multiple opposing perspectives and reconcile."""

    name: str = "debate"
    description: str = (
        "Analyze a question from three opposing perspectives (optimist, pessimist, "
        "pragmatist). Each perspective researches independently, then a reconciler "
        "identifies consensus, dissent, and blind spots, producing a balanced analysis. "
        "Best for: strategic decisions, risk assessment, evaluating proposals, "
        "identifying hidden assumptions."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question or proposal to debate.",
            },
        },
        "required": ["question"],
    }

    _llm: Any = None
    _flow_factory: Any = None

    def __init__(
        self,
        llm: Any = None,
        flow_factory: Any = None,
        **data: Any,
    ) -> None:
        super().__init__(**data)
        object.__setattr__(self, "_llm", llm)
        object.__setattr__(self, "_flow_factory", flow_factory)

    async def execute(self, question: str, **_: Any) -> ToolResult:
        if not self._llm:
            return ToolResult.error_result("DebateTool has no LLMPort — wire it via DI")

        t_start = time.monotonic()

        # 1. Dispatch three perspective agents
        tasks = []
        for p in _PERSPECTIVES:
            tasks.append({
                "task_id": f"debate-{p['role']}",
                "description": (
                    f"{p['framing']}\n\nResearch and analyze this question:\n\n{question}\n\n"
                    f"Produce findings from your {p['role']} perspective. Be thorough."
                ),
            })

        from weebot.tools.dispatch_agents import DispatchAgentsTool

        dispatcher = DispatchAgentsTool(flow_factory=self._flow_factory)
        dispatch_result = await dispatcher.execute(tasks=tasks, max_concurrency=3)
        sub_results = dispatch_result.data.get("results", [])

        # 2. Reconciler synthesizes
        viewpoints = []
        for r in sub_results:
            role = r.get("task_id", "").replace("debate-", "")
            summary = r.get("summary", "")
            viewpoints.append(
                Viewpoint(
                    role=role,
                    research_findings=summary,
                    key_claims=[],
                    confidence=0.7,
                )
            )

        # Build transcript for reconciler
        transcript_parts = []
        for v in viewpoints:
            transcript_parts.append(
                f"## {v.role.upper()}\n{v.research_findings[:2000]}"
            )
        transcript = "\n\n".join(transcript_parts)

        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": _RECONCILER_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"Question: {question}\n\n"
                            f"Perspective analyses:\n\n{transcript}\n\n"
                            "Reconcile these viewpoints."
                        ),
                    },
                ],
                temperature=TEMPERATURE_BALANCED,
                max_tokens=2048,
            )
            data = self._parse_json(response.content or "")
        except Exception as exc:
            logger.warning("Debate reconciler failed: %s — using raw merge", exc)
            data = {}

        elapsed = time.monotonic() - t_start

        synthesis = data.get(
            "synthesis",
            "\n\n".join(
                f"### {v.role.upper()}\n{v.research_findings}" for v in viewpoints
            ),
        )

        header = (
            f"## Debate Results\n"
            f"**Question:** {question[:200]}\n"
            f"**Perspectives:** optimist · pessimist · pragmatist "
            f"({elapsed:.1f}s)\n\n"
        )

        return ToolResult.success_result(
            output=header + synthesis,
            data={
                "question": question,
                "viewpoints": [v.model_dump() for v in viewpoints],
                "consensus": data.get("consensus", []),
                "dissent": data.get("dissent", []),
                "blind_spots": data.get("blind_spots", []),
                "synthesis": synthesis,
                "elapsed_seconds": elapsed,
            },
        )

    @staticmethod
    def _parse_json(content: str) -> dict:
        import json

        content = content.strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        if "```" in content:
            start = content.find("{")
            end = content.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(content[start:end])
        return {}
