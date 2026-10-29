"""SelfImprovementProposer — ask a model for an edit to a rule or contract file.

SelfImprover could only check and apply a patch someone else wrote; nothing wrote
one. This reads the target file and the most recent failure modes, asks the model
for the whole revised file, and turns the answer into a patch SelfImprover has
checked. It never applies anything: the ``improve`` CLI holds the patch until a
human applies it.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from weebot.domain.models.self_improvement import SelfImprovementPatch

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"```[\w-]*\n(.*?)```", re.DOTALL)

_PROMPT = """You maintain one configuration file of an AI agent.

File: {path}
Current content:
<<<
{content}
>>>

Recent failures of the agent (newest first):
{failures}

{goal}Revise the file so the agent avoids these failures. Keep its format, keep
everything that still applies, and change as little as needed. Reply with the
whole revised file in one fenced code block and nothing else."""


class SelfImprovementProposer:
    """Build a checked, unapplied patch for *target_file* from recent failures."""

    def __init__(self, llm: Any, improver: Any, trajectory_repo: Any | None = None) -> None:
        self._llm = llm
        self._improver = improver
        self._trajectories = trajectory_repo

    async def _failure_lines(self, limit: int = 8) -> str:
        if self._trajectories is None:
            return "(none recorded)"
        try:
            failures = await self._trajectories.recent_failures()
        except Exception as exc:
            logger.debug("Failure lookup skipped: %s", exc)
            return "(none recorded)"
        lines = []
        for t in failures[:limit]:
            modes = "; ".join(getattr(t, "failure_modes", [])[:3]) or "unspecified"
            lines.append(f"- {getattr(t, 'task_text', '')[:100]}: {modes}")
        return "\n".join(lines) or "(none recorded)"

    async def propose(self, target_file: str, goal: str = "") -> SelfImprovementPatch | None:
        """A validated patch, or None when the target or the answer is unusable."""
        if not self._improver._is_allowed_target(target_file):
            logger.warning("Target %s is not in the allowlist", target_file)
            return None
        path = Path(self._improver._project_root) / target_file
        content = await asyncio.to_thread(path.read_text, encoding="utf-8")
        prompt = _PROMPT.format(
            path=target_file,
            content=content,
            failures=await self._failure_lines(),
            goal=f"Goal: {goal}\n\n" if goal else "",
        )
        response = await self._llm.chat(messages=[{"role": "user", "content": prompt}])
        match = _FENCE.search(response.content or "")
        if match is None:
            logger.warning("The proposal reply had no fenced file; nothing proposed")
            return None
        patch = await self._improver.propose_patch(
            {"target_file": target_file, "current_content": content, "new_content": match.group(1)}
        )
        if patch is not None:
            patch.validation_score = await self._improver.validate_patch(patch)
        return patch
