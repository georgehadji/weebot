"""AutonomousLearningService — deployment-time skill distillation (Phase 1).

After a task completes, analyzes the trajectory with an LLM to extract a
reusable, generalizable procedure.  The result is stored as a *quarantined*
Skill in SkillStore — it is never injected live until it passes validation
and is promoted to ``candidate`` or ``trusted`` (Phase 1 trust model).

Architecture note:
  - This service is registered in DI as ``skill_distiller``.
  - It is called from MetaAnalysisState (post-summary hook).
  - When LIVE_SKILL_DISTILLATION_ENABLED is False, DI returns _NoOpDistiller
    (from ``weebot.application.di._learning``) so callers need no guard.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from weebot.config.constants import MAX_TOKENS_MODERATE, TEMPERATURE_BALANCED
from weebot.domain.models.skill import Skill, SkillMetadata, SkillProvenance

if TYPE_CHECKING:
    from weebot.application.ports.llm_port import LLMPort
    from weebot.infrastructure.persistence.skill_store import SkillStore

logger = logging.getLogger(__name__)

# ── LLM prompts ────────────────────────────────────────────────────────────────

_DISTILL_SYSTEM = (
    "You are a skill extraction specialist. Review completed task trajectories "
    "and encode reusable multi-step procedures as structured skills. "
    "Respond ONLY with valid JSON — no markdown fences, no commentary."
)

_DISTILL_PROMPT = """\
Review this completed task trajectory and decide whether it contains a skill worth encoding.

TRAJECTORY:
{trajectory}

A skill is worth creating if:
- It demonstrates a generalizable multi-step procedure (3 or more steps).
- The procedure is non-obvious and would help with similar future tasks.
- It is NOT a trivial single-tool operation or a one-off fix.

Respond with JSON only:
{{
  "worth_creating": true,
  "name": "kebab-case-skill-name",
  "description": "One sentence: when to use this skill and why.",
  "content": "Full SKILL.md markdown body with ## When to Use, ## Procedure (numbered steps), ## Notes sections."
}}

If the trajectory does NOT contain a reusable skill, respond:
{{
  "worth_creating": false,
  "name": "",
  "description": "",
  "content": ""
}}"""

# Maximum trajectory characters sent to the distiller LLM (cost guard).
_MAX_TRAJECTORY_CHARS = 3_000
# Minimum trajectory length before attempting distillation.
_MIN_TRAJECTORY_CHARS = 500
# Maximum skill name length after sanitisation.
_MAX_NAME_LEN = 50
# Regex for valid kebab-case skill name characters.
_NAME_RE = re.compile(r"[^a-z0-9-]")

# Singleton proposal tracker for anti-pattern detection across sessions
_proposal_tracker: Optional["ProposalTracker"] = None


def _get_proposal_tracker() -> "ProposalTracker":
    global _proposal_tracker
    if _proposal_tracker is None:
        from weebot.application.services.proposal_tracker import ProposalTracker
        _proposal_tracker = ProposalTracker(suppression_threshold=3)
    return _proposal_tracker


class AutonomousSkillCreator:
    """Distil a reusable skill from a completed task trajectory using an LLM.

    Replaces the original heuristic stub with a real LLM-backed distiller.
    Created skills are stored as ``quarantined`` in *skill_store* and are
    never injected into the live executor until they have been validated and
    promoted by the trust pipeline.
    """

    def __init__(
        self,
        llm: Optional["LLMPort"] = None,
        skill_store: Optional["SkillStore"] = None,
        skills_dir: Optional[str] = None,  # legacy param, ignored when skill_store provided
    ) -> None:
        self._llm = llm
        self._skill_store = skill_store

    async def analyze_session(
        self,
        session_id: str,
        trajectory: str,
    ) -> Optional[Skill]:
        """Analyze a completed trajectory and distil a quarantined skill.

        Args:
            session_id: The originating session ID (stored in provenance).
            trajectory: Human-readable summary of the task trajectory.

        Returns:
            A newly distilled ``Skill`` (trust=quarantined) persisted to
            *skill_store*, or ``None`` if no skill was warranted.
        """
        if not trajectory or len(trajectory) < _MIN_TRAJECTORY_CHARS:
            logger.debug("Trajectory too short for distillation (%d chars)", len(trajectory))
            return None
        if self._llm is None:
            logger.debug("No LLM configured — skipping distillation")
            return None

        parsed = await self._call_distiller(trajectory)
        if parsed is None:
            return None

        name, description, content = parsed

        prov = SkillProvenance(
            origin="distilled",
            session_id=session_id,
            created_at=datetime.now(timezone.utc),
        )
        meta = SkillMetadata(trust="quarantined", provenance=prov)
        skill = Skill(name=name, description=description, content=content, metadata=meta)

        # ── Anti-pattern guard: suppress identical proposals ──
        fp = _get_proposal_tracker().fingerprint(content)
        if not _get_proposal_tracker().record_and_check(fp):
            logger.info(
                "Anti-pattern guard suppressed skill '%s' (repeated proposal)", name
            )
            return None

        if self._skill_store is not None:
            try:
                await self._skill_store.save(skill)
                logger.info(
                    "Distilled quarantined skill '%s' from session %s",
                    name, session_id[:8],
                )
            except Exception as exc:
                logger.warning("Failed to persist distilled skill '%s': %s", name, exc)

        return skill

    async def _call_distiller(
        self, trajectory: str
    ) -> Optional[tuple[str, str, str]]:
        """Ask the LLM to extract a skill from *trajectory*.

        Returns (name, description, content) or None.
        """
        truncated = trajectory[:_MAX_TRAJECTORY_CHARS]
        prompt = _DISTILL_PROMPT.format(trajectory=truncated)
        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": _DISTILL_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=TEMPERATURE_BALANCED,
                max_tokens=MAX_TOKENS_MODERATE,
            )
            raw = response.content if hasattr(response, "content") else str(response)
            return _parse_distiller_response(raw)
        except Exception as exc:
            logger.warning("Skill distillation LLM call failed: %s", exc)
            return None


# ── parser (module-level so it's testable in isolation) ───────────────────────


def _parse_distiller_response(raw: str) -> Optional[tuple[str, str, str]]:
    """Extract (name, description, content) from the LLM JSON response.

    Returns None if the LLM decided not worth creating, or if parsing fails.
    """
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        logger.debug("Distiller response contained no JSON object")
        return None
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError as exc:
        logger.debug("Distiller JSON parse error: %s", exc)
        return None

    if not data.get("worth_creating", False):
        logger.debug("Distiller decided skill not worth creating")
        return None

    name: str = str(data.get("name", "")).strip().lower()
    description: str = str(data.get("description", "")).strip()
    content: str = str(data.get("content", "")).strip()

    # Sanitise name to kebab-case
    name = _NAME_RE.sub("-", name)[:_MAX_NAME_LEN].strip("-")
    # Collapse multiple consecutive hyphens
    name = re.sub(r"-{2,}", "-", name)

    if not name or not content:
        logger.debug("Distiller response missing name or content after sanitisation")
        return None

    return name, description, content


# ── legacy service (unchanged) ────────────────────────────────────────────────


class MemoryNudgeService:
    """Generates periodic nudges to persist important knowledge."""

    def __init__(self) -> None:
        pass

    async def check_and_nudge(self, active_sessions: list[str]) -> list[str]:
        nudges: list[str] = []
        if len(active_sessions) > 3:
            nudges.append(
                f"Found {len(active_sessions)} active sessions — "
                "consider consolidating or completing older ones."
            )
        return nudges

    async def generate_insight_nudge(self, session_summary: str) -> Optional[str]:
        if len(session_summary) > 500 and "tool" in session_summary.lower():
            return (
                "This session contains useful tool usage patterns. "
                "Would you like to save this as a skill?"
            )
        return None
