"""Unit tests for skill CLI commands.

Covers:
- weebot skill list displays discovered skills
- weebot skill list --active-only filters correctly
- weebot skill install copies a Weebot-format SKILL.md
- weebot skill install rejects unknown formats
- skill update --source agentskills routing (Fix 2)
- BM25 rebuild after install (Fix 4)

NOTE: cli.main imports trigger langchain. To avoid hangs, we defer
the import inside each test method rather than at module level.
"""
import pytest
from click.testing import CliRunner


class TestSkillListCLI:
    """Validates the `weebot skill list` command."""

    @pytest.fixture
    def populated_skills(self, tmp_path, monkeypatch):
        """Create a temp dir with a sample skill and chdir to it."""
        skills_dir = tmp_path / ".weebot" / "skills" / "test-skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: A test skill\n---\n\nHello world"
        )
        monkeypatch.chdir(tmp_path)
        yield

    def test_list_shows_all_skills(self, populated_skills):
        """skill list shows installed skills in a table."""
        from cli.commands.skills import skill_list

        runner = CliRunner()
        result = runner.invoke(skill_list)

        assert result.exit_code == 0
        assert "test-skill" in result.output
        assert "A test skill" in result.output

    def test_list_active_when_no_env_set(self, populated_skills):
        """skill list --active-only shows skills with no env requirements."""
        from cli.commands.skills import skill_list

        runner = CliRunner()
        result = runner.invoke(skill_list, ["--active-only"])

        assert result.exit_code == 0
        assert "test-skill" in result.output

    def test_list_empty_when_no_skills(self, tmp_path, monkeypatch):
        """skill list on an empty directory shows no skills table."""
        monkeypatch.chdir(tmp_path)

        # Mock SkillRegistry to return empty so global skills don't leak in
        class FakeRegistry:
            def load_all(self): pass
            def list_skills(self): return []
            def get_active_skills(self): return []

        monkeypatch.setattr(
            "weebot.application.skills.skill_registry.SkillRegistry",
            lambda: FakeRegistry(),
        )

        from cli.commands.skills import skill_list

        runner = CliRunner()
        result = runner.invoke(skill_list)

        assert result.exit_code == 0
        assert "No skills found" in result.output


class TestSkillInstallCLI:
    """Validates the `weebot skill install` command."""

    def test_installs_weebot_skill(self, tmp_path, monkeypatch):
        """Installing a Weebot SKILL.md copies it to .weebot/skills/."""
        source = tmp_path / "my-skill" / "SKILL.md"
        source.parent.mkdir()
        source.write_text(
            "---\nname: my-skill\ndescription: My custom skill\n---\n\nSkill content"
        )

        monkeypatch.chdir(tmp_path)
        from cli.commands.skills import skill_install

        runner = CliRunner()
        result = runner.invoke(skill_install, [str(source.parent)])

        assert result.exit_code == 0
        assert "my-skill" in result.output
        assert (tmp_path / ".weebot" / "skills" / "my-skill" / "SKILL.md").exists()

    def test_installs_weebot_skill_from_file(self, tmp_path, monkeypatch):
        """Installing from a SKILL.md file path works with --name."""
        source = tmp_path / "SKILL.md"
        source.write_text(
            "---\nname: file-skill\ndescription: From file\n---\n\nContent"
        )

        monkeypatch.chdir(tmp_path)
        from cli.commands.skills import skill_install

        runner = CliRunner()
        # Use --name to avoid ambiguity with the source path stem
        result = runner.invoke(skill_install, [str(source), "--name", "file-skill"])

        assert result.exit_code == 0
        assert "file-skill" in result.output
        assert (tmp_path / ".weebot" / "skills" / "file-skill" / "SKILL.md").exists()

    def test_install_rejects_unknown_format(self, tmp_path, monkeypatch):
        """Installing an unknown file format shows an error."""
        unknown = tmp_path / "random.txt"
        unknown.write_text("garbage content")

        monkeypatch.chdir(tmp_path)
        from cli.commands.skills import skill_install

        runner = CliRunner()
        result = runner.invoke(skill_install, [str(unknown)])

        assert result.exit_code == 0
        assert "Cannot determine format" in result.output or "cannot determine" in result.output.lower()

    def test_install_with_custom_name(self, tmp_path, monkeypatch):
        """--name overrides the auto-detected skill name."""
        source = tmp_path / "SKILL.md"
        source.write_text(
            "---\nname: original-name\ndescription: Override test\n---\n\nContent"
        )

        monkeypatch.chdir(tmp_path)
        from cli.commands.skills import skill_install

        runner = CliRunner()
        result = runner.invoke(skill_install, [str(source), "--name", "custom-name"])

        assert result.exit_code == 0
        assert "custom-name" in result.output
        assert not (tmp_path / ".weebot" / "skills" / "original-name").exists()
        assert (tmp_path / ".weebot" / "skills" / "custom-name" / "SKILL.md").exists()


# ── Fix 2: CLI source routing tests ────────────────────────────────


class TestSkillUpdateSourceRouting:
    """Validates `skill update --source` routing (Fix 2).

    The adapters are imported inside _run(), so we monkeypatch at the
    actual adapter module path rather than cli.commands.skills.
    """

    def test_agentskills_source_uses_awesome_adapter(self, monkeypatch, tmp_path):
        """--source agentskills instantiates AwesomeAgentSkillsAdapter."""
        monkeypatch.chdir(tmp_path)

        captured = {}

        class FakeAdapter:
            def __init__(self, *a, **kw):
                captured["used"] = "agentskills"
            async def fetch_index(self):
                return []
            async def close(self):
                pass

        # Patch at the module where it lives so the import inside _run() picks it up
        monkeypatch.setattr(
            "weebot.infrastructure.adapters.awesome_agent_skills_adapter.AwesomeAgentSkillsAdapter",
            FakeAdapter,
        )

        from cli.commands.skills import skill_update

        runner = CliRunner()
        result = runner.invoke(skill_update, ["--source", "agentskills"])
        assert result.exit_code == 0
        assert captured.get("used") == "agentskills"

    def test_skillhub_source_uses_github_adapter(self, monkeypatch, tmp_path):
        """Default --source skillhub instantiates GitHubSkillIndexAdapter."""
        monkeypatch.chdir(tmp_path)

        captured = {}

        class FakeAdapter:
            def __init__(self, *a, **kw):
                captured["used"] = "skillhub"
            async def fetch_index(self):
                return []
            async def close(self):
                pass

        monkeypatch.setattr(
            "weebot.infrastructure.adapters.skill_index_github.GitHubSkillIndexAdapter",
            FakeAdapter,
        )

        from cli.commands.skills import skill_update

        runner = CliRunner()
        result = runner.invoke(skill_update)  # default is --source skillhub
        assert result.exit_code == 0
        assert captured.get("used") == "skillhub"


# ── Fix 4: BM25 rebuild tests ──────────────────────────────────────


class TestSkillInstallBM25Rebuild:
    """Validates BM25 index rebuild after skill install/update (Fix 4)."""

    def test_install_triggers_bm25_rebuild(self, tmp_path, monkeypatch):
        """Successful install calls _rebuild_bm25_index."""
        import cli.commands.skills as skills_module

        rebuild_called = []

        def fake_rebuild(rebuild_console):
            rebuild_called.append(True)

        monkeypatch.setattr(skills_module, "_rebuild_bm25_index", fake_rebuild)

        source = tmp_path / "SKILL.md"
        source.write_text(
            "---\nname: test-skill\ndescription: A test\n---\n\nContent"
        )

        monkeypatch.chdir(tmp_path)
        from cli.commands.skills import skill_install

        runner = CliRunner()
        result = runner.invoke(skill_install, [str(source)])

        assert result.exit_code == 0
        assert rebuild_called, "_rebuild_bm25_index was not called after install"
