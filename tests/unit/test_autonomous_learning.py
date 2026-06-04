"""Unit tests for Self-Improving Learning Loop (Hermes M1)."""
import pytest


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
    async def test_skill_for_long_trajectory(self):
        from weebot.application.services.autonomous_learning import (
            AutonomousSkillCreator,
        )
        creator = AutonomousSkillCreator()
        trajectory = (
            "Tool call: bash executed ls\n"
            "Tool call: python executed analysis\n"
            "Tool call: bash executed grep\n"
            "Processing data with multiple steps\n"
            "Validation completed successfully\n"
            "Generation of report started\n"
            "Extraction of key metrics\n"
        )
        skill = await creator.analyze_session("test-2", trajectory)
        assert skill is not None
        assert skill.name is not None
        assert "Procedure" in skill.content

    @pytest.mark.asyncio
    async def test_save_skill_writes_file(self, tmp_path):
        from weebot.application.services.autonomous_learning import (
            AutonomousSkillCreator,
        )
        from weebot.domain.models.skill import Skill

        creator = AutonomousSkillCreator(skills_dir=str(tmp_path / "skills"))
        skill = Skill(name="test-skill", description="Test", content="# Test\n\nContent")
        path = await creator.save_skill(skill)
        assert path.exists()
        assert path.read_text().startswith("---")

    def test_detect_repetitive_patterns_empty(self):
        from weebot.application.services.autonomous_learning import (
            AutonomousSkillCreator,
        )
        assert AutonomousSkillCreator._detect_repetitive_patterns("") is False


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
