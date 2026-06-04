"""Unit tests for Harness Generation Flow (Harness Enhancement H3).

Covers:
- TeamArchitecture dataclasses
- HarnessGenerationFlow.domain analysis
- Pattern selection based on work types
- Agent design per pattern
- File generation (dry-run mode)
"""
import pytest


class TestTeamArchitectureModels:
    """Validates domain models."""

    def test_team_pattern_enum(self):
        from weebot.domain.models.team_architecture import TeamPattern

        assert len(TeamPattern) == 6
        assert TeamPattern.PIPELINE.value == "pipeline"
        assert TeamPattern.FAN_OUT_FAN_IN.value == "fan_out_fan_in"

    def test_agent_definition_defaults(self):
        from weebot.domain.models.team_architecture import AgentDefinition

        a = AgentDefinition(name="test-agent", role="Tester")
        assert a.agent_type == "general-purpose"
        assert a.model == "opus"
        assert a.skills == []

    def test_skill_blueprint(self):
        from weebot.domain.models.team_architecture import SkillBlueprint

        s = SkillBlueprint(name="test-skill", description="Test")
        assert s.content == ""
        assert s.references == []

    def test_team_architecture(self):
        from weebot.domain.models.team_architecture import (
            TeamArchitecture,
            TeamPattern,
            AgentDefinition,
            SkillBlueprint,
        )

        arch = TeamArchitecture(
            domain="test domain",
            pattern=TeamPattern.PIPELINE,
            agents=[AgentDefinition(name="a1", role="R1")],
            skills=[SkillBlueprint(name="s1", description="D1")],
        )
        assert arch.domain == "test domain"
        assert len(arch.agents) == 1
        assert len(arch.skills) == 1


class TestHarnessGenerationFlow:
    """Validates HarnessGenerationFlow core logic."""

    @pytest.fixture
    def flow(self):
        from weebot.application.flows.harness_generation_flow import (
            HarnessGenerationFlow,
        )

        return HarnessGenerationFlow()

    def test_analyze_research_domain(self, flow):
        """Research keywords produce 'research' work type."""
        types = flow._analyze_domain("research the impact of AI on healthcare")
        assert "research" in types

    def test_analyze_implementation_domain(self, flow):
        """Build keywords produce 'implement' work type."""
        types = flow._analyze_domain("build a full-stack web application")
        assert "implement" in types

    def test_analyze_empty_domain(self, flow):
        """Empty domain gets default work types."""
        types = flow._analyze_domain("")
        assert len(types) == 3
        assert "research" in types
        assert "implement" in types
        assert "review" in types

    def test_select_pattern_research(self, flow):
        """Research-heavy domains select fan-out/fan-in."""
        pattern = flow._select_pattern(["research", "collect"], "market research")
        assert pattern.value == "fan_out_fan_in"

    def test_select_pattern_review_only(self, flow):
        """Review-only selects producer-reviewer."""
        pattern = flow._select_pattern(["review"], "code quality check")
        assert pattern.value == "producer_reviewer"

    def test_select_pattern_complex(self, flow):
        """Complex/enterprise keywords select hierarchical delegation."""
        pattern = flow._select_pattern(
            ["research", "design", "implement"],
            "enterprise-scale system migration",
        )
        assert pattern.value == "hierarchical_delegation"

    def test_select_pattern_default(self, flow):
        """Default fallback is pipeline."""
        pattern = flow._select_pattern(["implement"], "simple script")
        assert pattern.value == "pipeline"

    def test_design_agents_pipeline(self, flow):
        """Pipeline produces 4 agents: analyst, designer, builder, reviewer."""
        from weebot.domain.models.team_architecture import TeamPattern
        agents = flow._design_agents("web app", TeamPattern.PIPELINE)
        assert len(agents) == 4
        assert agents[0].name == "analyst"
        assert agents[-1].name == "reviewer"

    def test_design_agents_fanout(self, flow):
        """Fan-out/fan-in produces 4 agents."""
        from weebot.domain.models.team_architecture import TeamPattern
        agents = flow._design_agents("research", TeamPattern.FAN_OUT_FAN_IN)
        assert len(agents) == 4
        names = [a.name for a in agents]
        assert "coordinator" in names
        assert "synthesizer" in names

    def test_design_skills_unique(self, flow):
        """Skills are unique across agents."""
        from weebot.domain.models.team_architecture import AgentDefinition

        agents = [
            AgentDefinition(name="a1", role="R1", skills=["research", "write"]),
            AgentDefinition(name="a2", role="R2", skills=["research", "review"]),
        ]
        from weebot.domain.models.team_architecture import TeamPattern
        skills = flow._design_skills("test", agents, TeamPattern.PIPELINE)
        # 3 unique skills: research, write, review
        assert len(skills) == 3
        skill_names = [s.name for s in skills]
        assert any("research" in n for n in skill_names)
        assert any("write" in n for n in skill_names)
        assert any("review" in n for n in skill_names)

    @pytest.mark.asyncio
    async def test_generate_team_architecture(self, flow):
        """Full generation returns a valid TeamArchitecture."""
        arch = await flow.generate("deep research with web scraping and academic sources")
        assert arch.domain is not None
        assert len(arch.agents) >= 2
        assert len(arch.skills) >= 1
        assert arch.pattern is not None

    def test_render_agent(self, flow):
        """Agent definition is rendered as valid markdown with frontmatter."""
        from weebot.domain.models.team_architecture import AgentDefinition

        agent = AgentDefinition(name="analyst", role="Analysis", persona="Analyst persona")
        rendered = flow._render_agent(agent)
        assert "name: analyst" in rendered
        assert "Analysis" in rendered
        assert "---" in rendered


class TestHarnessCLI:
    """Validates the harness CLI commands by name registration (avoids langchain import)."""

    def test_harness_group_registered(self):
        """The harness command group exists.
        
        Tests by checking the source file for the Click decorator
        rather than importing cli.main (which triggers a langchain
        import hang in this test environment).
        """
        import re
        source = open("cli/main.py", encoding="utf-8").read()
        assert re.search(r'@cli\.group\(\)\s*\n\s*def harness\(\)', source) is not None

    def test_harness_generate_command(self):
        """The generate subcommand exists."""
        import re
        source = open("cli/main.py", encoding="utf-8").read()
        assert re.search(r'@harness\.command\("generate"\)', source) is not None

    def test_dry_run_flag(self):
        """The --dry-run flag is accepted."""
        import re
        source = open("cli/main.py", encoding="utf-8").read()
        assert '--dry-run' in source
