"""Unit tests for Hermes-inspired Skill enhancements (M3, M4, M11).

Covers:
- M3: Platform-specific skills (platforms field, is_compatible_with_platform)
- M4: Skill config system (config field, get_missing_config)
- M11: Conditional activation (requires_toolsets, fallback_for_toolsets)
"""
import sys
import pytest


class TestSkillPlatformCompatibility:
    """M3: Platform-specific skills."""

    @pytest.fixture
    def skill(self):
        from weebot.domain.models.skill import Skill, SkillMetadata

        return Skill(
            name="macos-only",
            description="macOS only skill",
            content="",
            metadata=SkillMetadata(platforms=["macos"]),
        )

    def test_compatible_with_declared_platform(self, skill):
        """Skill declared for macos is compatible with macos."""
        assert skill.is_compatible_with_platform("macos") is True

    def test_incompatible_with_undeclared_platform(self, skill):
        """Skill declared for macos is NOT compatible with linux."""
        assert skill.is_compatible_with_platform("linux") is False
        assert skill.is_compatible_with_platform("windows") is False

    def test_no_platforms_all(self):
        """Skill with empty platforms list is compatible everywhere."""
        from weebot.domain.models.skill import Skill

        skill = Skill(name="all-platforms", description="", content="")
        assert skill.is_compatible_with_platform("macos") is True
        assert skill.is_compatible_with_platform("linux") is True
        assert skill.is_compatible_with_platform("windows") is True

    def test_detect_platform(self):
        """detect_platform returns a known string."""
        from weebot.domain.models.skill import Skill

        platform = Skill.detect_platform()
        assert platform in ("macos", "linux", "windows")


class TestSkillConfigSystem:
    """M4: Skill config system."""

    def test_get_missing_config_no_config(self):
        """Skill with no config returns empty list."""
        from weebot.domain.models.skill import Skill

        skill = Skill(name="no-config", description="", content="")
        assert skill.get_missing_config() == []

    def test_get_missing_config_with_defaults(self):
        """Config entries with defaults are not required."""
        from weebot.domain.models.skill import Skill, SkillMetadata

        skill = Skill(
            name="with-defaults",
            description="",
            content="",
            metadata=SkillMetadata(config=[
                {"key": "my.setting", "default": "value", "description": "A setting"},
            ]),
        )
        missing = skill.get_missing_config()
        assert len(missing) == 0

    def test_get_missing_config_required_fields(self):
        """Config entries without defaults are reported as missing."""
        from weebot.domain.models.skill import Skill, SkillMetadata

        skill = Skill(
            name="required-config",
            description="",
            content="",
            metadata=SkillMetadata(config=[
                {"key": "api.key", "description": "API key", "prompt": "Enter API key"},
            ]),
        )
        missing = skill.get_missing_config()
        assert len(missing) == 1
        assert missing[0]["key"] == "api.key"


class TestSkillConditionalActivation:
    """M11: Fallback and toolset requirements."""

    def test_no_requirements_always_available(self):
        """Skill with no requires_toolsets is always available."""
        from weebot.domain.models.skill import Skill

        skill = Skill(name="general", description="", content="")
        assert skill.requires_toolset(set()) is True
        assert skill.requires_toolset({"web", "terminal"}) is True

    def test_requires_toolsets_all_present(self):
        """Skill requires 'web' and 'terminal': available when both present."""
        from weebot.domain.models.skill import Skill, SkillMetadata

        skill = Skill(
            name="web-skill",
            description="",
            content="",
            metadata=SkillMetadata(requires_toolsets=["web", "terminal"]),
        )
        assert skill.requires_toolset({"web", "terminal", "filesystem"}) is True

    def test_requires_toolsets_missing(self):
        """Skill requires 'web': unavailable when web is not in set."""
        from weebot.domain.models.skill import Skill, SkillMetadata

        skill = Skill(
            name="web-skill",
            description="",
            content="",
            metadata=SkillMetadata(requires_toolsets=["web"]),
        )
        assert skill.requires_toolset({"terminal"}) is False

    def test_fallback_when_premium_missing(self):
        """Skill is a fallback when fallback_for_toolsets has missing entries."""
        from weebot.domain.models.skill import Skill, SkillMetadata

        skill = Skill(
            name="free-search",
            description="",
            content="",
            metadata=SkillMetadata(fallback_for_toolsets=["premium-search"]),
        )
        assert skill.is_fallback_for({"terminal"}) is True
        assert skill.is_fallback_for({"terminal", "premium-search"}) is False

    def test_no_fallback_no_activation(self):
        """Skill with no fallback_for_toolsets never acts as fallback."""
        from weebot.domain.models.skill import Skill

        skill = Skill(name="normal", description="", content="")
        assert skill.is_fallback_for({"anything"}) is False
        assert skill.is_fallback_for(set()) is False


class TestSkillRegistryNewFields:
    """Validates that registry parses new fields from frontmatter."""

    def test_registry_parses_platforms(self, tmp_path, monkeypatch):
        """SKILL.md with platforms field is parsed correctly."""
        from weebot.application.skills.skill_registry import SkillRegistry

        skills_root = tmp_path / ".weebot" / "skills"
        skill_dir = skills_root / "platform-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: platform-skill\n"
            "description: Test\n"
            "metadata:\n"
            "  hermes:\n"
            "    platforms: [macos]\n"
            "---\n"
            "\nBody"
        )

        monkeypatch.chdir(tmp_path)
        registry = SkillRegistry(search_paths=[skills_root])
        registry.load_all()

        skill = registry.get_skill("platform-skill")
        assert skill is not None
        assert skill.metadata.platforms == ["macos"]

    def test_registry_parses_config(self, tmp_path, monkeypatch):
        """SKILL.md with config schema is parsed correctly."""
        from weebot.application.skills.skill_registry import SkillRegistry

        skills_root = tmp_path / ".weebot" / "skills"
        skill_dir = skills_root / "config-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: config-skill\n"
            "description: Test\n"
            "metadata:\n"
            "  hermes:\n"
            "    config:\n"
            "      - key: api.key\n"
            "        description: API key\n"
            "        prompt: Enter your API key\n"
            "---\n"
            "\nBody"
        )

        monkeypatch.chdir(tmp_path)
        registry = SkillRegistry(search_paths=[skills_root])
        registry.load_all()

        skill = registry.get_skill("config-skill")
        assert skill is not None
        assert len(skill.metadata.config) == 1
        assert skill.metadata.config[0]["key"] == "api.key"
