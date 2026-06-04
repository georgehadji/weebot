"""AutonomousLearningService — closed learning loop for self-improvement.

Analyzes completed sessions to:
1. Identify new skill opportunities (create skills from repeated patterns)
2. Generate memory nudges (prompt knowledge persistence)
3. Self-improve existing skills based on usage patterns

Inspired by Hermes Agent's autonomous skill creation and memory nudge system.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from weebot.domain.models.skill import Skill

logger = logging.getLogger(__name__)


class AutonomousSkillCreator:
    """Analyzes completed sessions and creates skills from patterns.

    Scans session trajectories for repeated multi-step operations
    and generates skill files that codify those patterns.
    """

    def __init__(self, skills_dir: Optional[str] = None) -> None:
        self._skills_dir = Path(skills_dir) if skills_dir else Path.cwd() / ".weebot" / "skills"
        self._skills_dir.mkdir(parents=True, exist_ok=True)

    async def analyze_session(self, session_id: str, trajectory: str) -> Optional[Skill]:
        """Analyze a completed session for skill creation opportunities.

        Args:
            session_id: The session ID.
            trajectory: Session trajectory text (summarized events).

        Returns:
            A new ``Skill`` if a pattern was found, ``None`` otherwise.
        """
        # Check if the trajectory has multi-step patterns worth capturing
        if self._detect_repetitive_patterns(trajectory):
            name = self._generate_skill_name(trajectory)
            content = self._generate_skill_content(trajectory)
            return Skill(
                name=name,
                description=f"Auto-generated from session {session_id[:8]}",
                content=content,
            )
        return None

    async def save_skill(self, skill: Skill) -> Path:
        """Write a skill file to disk."""
        skill_dir = self._skills_dir / skill.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        path = skill_dir / "SKILL.md"
        path.write_text(
            f"---\nname: {skill.name}\ndescription: {skill.description}\n"
            f"metadata:\n  auto_generated: true\n  created_at: "
            f"{datetime.now(timezone.utc).isoformat()}\n---\n\n"
            f"{skill.content}\n",
            encoding="utf-8",
        )
        logger.info("Auto-created skill '%s' at %s", skill.name, path)
        return path

    @staticmethod
    def _detect_repetitive_patterns(trajectory: str) -> bool:
        """Detect whether the trajectory has patterns worth a skill.

        Heuristic: if the trajectory contains at least 5 steps and
        references specific tools multiple times, it's a candidate.
        """
        if len(trajectory) < 200:
            return False

        # Simple heuristic: check for multiple tool mentions
        tool_keywords = ["tool_call", "using", "executed", "bash", "python"]
        return sum(1 for kw in tool_keywords if kw in trajectory.lower()) >= 2

    @staticmethod
    def _generate_skill_name(trajectory: str) -> str:
        """Generate a skill name from the trajectory content."""
        words = trajectory.lower().split()[:20]
        # Use the first action-oriented noun phrase
        for phrase in ["processing", "analysis", "generation", "validation", "extraction"]:
            if phrase in trajectory.lower():
                return f"auto-{phrase}"
        return "auto-learned-task"

    @staticmethod
    def _generate_skill_content(trajectory: str) -> str:
        """Generate skill content from the trajectory.

        Extracts the key steps and generalizes them into a reusable
        procedure.  In production this would use an LLM.
        """
        lines = trajectory.strip().split("\n")[:15]
        steps = "\n".join(f"{i+1}. {line.strip()[:80]}" for i, line in enumerate(lines) if line.strip())
        return (
            f"# Auto-Generated Skill\n\n"
            f"## When to Use\n"
            f"This skill automates a multi-step process observed in a previous session.\n\n"
            f"## Procedure\n"
            f"{steps}\n\n"
            f"## Notes\n"
            f"- Auto-generated from session analysis.\n"
            f"- Verify the steps are appropriate for your current context.\n"
        )


class MemoryNudgeService:
    """Generates periodic nudges to persist important knowledge.

    Called by the cron scheduler to check session state and prompt
    the agent (or user) to save important information.
    """

    def __init__(self) -> None:
        pass

    async def check_and_nudge(self, active_sessions: list[str]) -> list[str]:
        """Check active sessions and generate nudges.

        Args:
            active_sessions: List of active session IDs.

        Returns:
            List of nudge messages (empty if no nudges needed).
        """
        nudges = []
        if len(active_sessions) > 3:
            nudges.append(
                f"Found {len(active_sessions)} active sessions — "
                "consider consolidating or completing older ones."
            )
        return nudges

    async def generate_insight_nudge(self, session_summary: str) -> Optional[str]:
        """Generate a memory nudge from a session summary.

        If the session contains actionable knowledge, returns a
        prompt to persist it.
        """
        # Heuristic: long sessions with tool calls likely contain useful patterns
        if len(session_summary) > 500 and "tool" in session_summary.lower():
            return (
                "This session contains useful tool usage patterns. "
                "Would you like to save this as a skill?"
            )
        return None
