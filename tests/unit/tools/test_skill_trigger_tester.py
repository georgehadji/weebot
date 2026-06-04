"""Unit tests for Skill Trigger Testing (Harness Enhancement H4).

Covers:
- SkillTriggerTester generates should-trigger queries from skill description
- SkillTriggerTester generates should-NOT-trigger queries
- TriggerTestReport computes correct pass rates
- CLI `skill test` command exists and runs
"""
import pytest


class TestSkillTriggerTester:
    """Validates SkillTriggerTester core logic."""

    @pytest.fixture
    def skill(self):
        from weebot.domain.models.skill import Skill

        return Skill(
            name="pdf-processor",
            description="PDF file reading, text extraction, merge, split, "
                        "rotate, watermark, encrypt. ALL PDF operations. "
                        "When the user mentions .pdf files you MUST use this skill.",
            content="Process PDFs...",
        )

    @pytest.mark.asyncio
    async def test_generates_should_trigger_queries(self, skill):
        """Should-trigger queries contain keywords from the description."""
        from weebot.application.services.skill_trigger_tester import (
            SkillTriggerTester,
        )

        tester = SkillTriggerTester()
        report = await tester.test_skill(skill, num_should=3, num_should_not=3)

        assert len(report.should_triggers) == 3
        assert len(report.should_not_triggers) == 3
        assert report.total == 6

    @pytest.mark.asyncio
    async def test_should_trigger_queries_match_description(self, skill):
        """Should-trigger queries should actually trigger (contain keywords)."""
        from weebot.application.services.skill_trigger_tester import (
            SkillTriggerTester,
        )

        tester = SkillTriggerTester()
        report = await tester.test_skill(skill, num_should=5, num_should_not=3)

        # At least some should-trigger queries should actually trigger
        triggered_count = sum(1 for r in report.should_triggers if r.actual_triggered)
        assert triggered_count >= 2, (
            f"Only {triggered_count}/5 should-trigger queries actually triggered"
        )

    @pytest.mark.asyncio
    async def test_should_not_trigger_queries_do_not_match(self, skill):
        """Should-NOT-trigger queries do not trigger the skill."""
        from weebot.application.services.skill_trigger_tester import (
            SkillTriggerTester,
        )

        tester = SkillTriggerTester()
        report = await tester.test_skill(skill, num_should=3, num_should_not=3)

        for result in report.should_not_triggers:
            assert result.expected_trigger is False
            # These generic queries should NOT trigger a PDF skill
            assert result.actual_triggered is False

    @pytest.mark.asyncio
    async def test_pass_rate_calculation(self, skill):
        """Pass rate reflects correct results."""
        from weebot.application.services.skill_trigger_tester import (
            SkillTriggerTester,
        )

        tester = SkillTriggerTester()
        report = await tester.test_skill(skill, num_should=5, num_should_not=5)

        assert report.pass_rate >= 0.5  # Should-trigger should work
        assert 0.0 <= report.pass_rate <= 1.0

    @pytest.mark.asyncio
    async def test_empty_skill_name(self):
        """A skill with no name or description generates safe results."""
        from weebot.domain.models.skill import Skill
        from weebot.application.services.skill_trigger_tester import (
            SkillTriggerTester,
        )

        skill = Skill(name="", description="", content="")
        tester = SkillTriggerTester()
        report = await tester.test_skill(skill, num_should=2, num_should_not=2)

        assert report.total == 4
        assert report.pass_rate >= 0


class TestSkillTestCLI:
    """Validates the `weebot skill test` command."""

    def test_command_registered(self):
        """The skill test command exists in the CLI."""
        from cli.main import cli

        skill_group = cli.commands.get("skill")
        assert skill_group is not None
        commands = list(skill_group.commands.keys())
        assert "test" in commands

    def test_verbose_flag_accepted(self):
        """The --verbose flag is accepted."""
        from cli.main import skill_test

        import click
        for param in skill_test.params:
            if isinstance(param, click.Option) and "--verbose" in param.opts:
                assert param.is_flag
                return
        pytest.fail("--verbose flag not found on skill_test")
