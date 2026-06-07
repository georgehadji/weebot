"""SynthesizerAgent — clusters and merges results from parallel swarm agents.

Called after dispatch_parallel_tasks completes.  Takes the raw per-agent
summaries, groups related findings by topic, identifies consensus and
dissent, and produces a structured SwarmResult with a human-readable
synthesis report.

Implements the 'clustering agent' and 'synthesizer' patterns from the
agent swarm literature (Kimi K2.5 style).
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.swarm import SwarmResult

logger = logging.getLogger(__name__)

_SYNTHESIS_SYSTEM = """You are a research synthesizer. You receive findings from
multiple independent research agents who investigated different aspects
of the same question. Your job:

1. CLUSTER related findings — group similar observations across agents.
2. IDENTIFY consensus — what do multiple agents agree on?
3. IDENTIFY dissent — where do agents disagree or offer conflicting info?
4. IDENTIFY blind spots — what important angle did NO agent cover?
5. PRODUCE a synthesis — a 3-5 paragraph report integrating all findings
   with citations to which agent found what.

Return ONLY a JSON object:
{
  "clusters": [{"label": "...", "members": ["agent_role_1", "agent_role_2"], "insight": "..."}],
  "consensus": ["point 1", "point 2"],
  "dissent": [{"topic": "...", "views": {"role_a": "...", "role_b": "..."}}],
  "blind_spots": ["angle that was missed"],
  "synthesis": "3-5 paragraph integrated report...",
  "confidence": 0.85
}"""


class SynthesizerAgent:
    """Cluster and merge swarm agent results into a structured report."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def synthesize(
        self,
        prompt: str,
        results: list[dict],
        strategy: str = "cluster",
        model: Optional[str] = None,
    ) -> SwarmResult:
        """Synthesize parallel agent results into a SwarmResult.

        Args:
            prompt: The original user prompt.
            results: List of per-agent summaries:
                [{"role": "...", "summary": "...", "task_id": "..."}]
            strategy: 'cluster', 'merge', or 'vote'.
            model: Optional model override.

        Returns:
            SwarmResult with clusters, consensus, dissent, and synthesis.
        """
        if not results:
            return SwarmResult(
                prompt=prompt,
                synthesis="No results were produced by the swarm agents.",
            )

        t_start = time.monotonic()

        # Build a compact transcript for the synthesizer LLM
        transcript_parts = []
        for r in results:
            role = r.get("role", "unknown")
            summary = r.get("summary", "")[:1500]
            transcript_parts.append(f"## {role}\n{summary}")

        transcript = "\n\n".join(transcript_parts)

        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": _SYNTHESIS_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"Original question: {prompt}\n\n"
                            f"Agent findings:\n\n{transcript}\n\n"
                            f"Synthesize using '{strategy}' strategy."
                        ),
                    },
                ],
                model=model,
                temperature=TEMPERATURE_BALANCED,
                max_tokens=2048,
            )

            data = self._parse_json(response.content or "")
        except Exception as exc:
            logger.warning("Synthesizer LLM call failed: %s — using raw merge", exc)
            data = self._raw_merge(results)

        elapsed = time.monotonic() - t_start

        return SwarmResult(
            prompt=prompt,
            sub_results=results,
            clusters=data.get("clusters", []),
            synthesis=data.get("synthesis", self._fallback_synthesis(results)),
            elapsed_seconds=elapsed,
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

    @staticmethod
    def _raw_merge(results: list[dict]) -> dict:
        """Fallback: concatenate summaries without LLM synthesis."""
        parts = []
        for r in results:
            role = r.get("role", "agent")
            summary = r.get("summary", "")
            parts.append(f"**{role}**: {summary}")
        return {
            "clusters": [],
            "synthesis": "\n\n".join(parts),
        }

    @staticmethod
    def _fallback_synthesis(results: list[dict]) -> str:
        parts = []
        for r in results:
            parts.append(f"### {r.get('role', 'Agent')}\n{r.get('summary', '(no output)')}")
        return "\n\n".join(parts) if parts else "(no results)"
