"""Unit tests for Self-Improving Learning Loop (Hermes M1 → Memento Phase 1).

The original heuristic distiller (save_skill / _detect_repetitive_patterns)
was replaced by an LLM-backed distiller in Phase 1.  Behavioural coverage of
the new distiller lives in tests/unit/domain/models/test_skill_phase1.py; the
tests here cover only the no-LLM and short-trajectory guard paths.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestAutonomousSkillCreator:
    @pytest.mark.asyncio
    async def test_no_skill_for_short_trajectory(self):
        from weebot.application.services.autonomous_learning import (
            AutonomousSkillCreator,
        )
        creator = AutonomousSkillCreator()
        skill = await creator.analyze_session("test-1", "short")
        assert skill is None

    @pytest.mark.asyncio
    async def test_no_skill_without_llm(self):
        """A long trajectory still yields nothing when no LLM is configured."""
        from weebot.application.services.autonomous_learning import (
            AutonomousSkillCreator,
        )
        creator = AutonomousSkillCreator(llm=None)
        trajectory = "step detail line\n" * 60  # > _MIN_TRAJECTORY_CHARS
        skill = await creator.analyze_session("test-2", trajectory)
        assert skill is None


class TestMemoryNudgeService:
    @pytest.mark.asyncio
    async def test_no_nudge_for_few_sessions(self):
        from weebot.application.services.autonomous_learning import (
            MemoryNudgeService,
        )
        service = MemoryNudgeService()
        nudges = await service.check_and_nudge(["s1", "s2"])
        assert nudges == []

    @pytest.mark.asyncio
    async def test_nudge_for_many_sessions(self):
        from weebot.application.services.autonomous_learning import (
            MemoryNudgeService,
        )
        service = MemoryNudgeService()
        nudges = await service.check_and_nudge(["s1", "s2", "s3", "s4", "s5"])
        assert len(nudges) > 0
        assert "consolidating" in nudges[0].lower()
