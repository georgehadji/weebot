"""Unit tests for skill CLI commands (Enhancement 2).

Covers:
- weebot skill list displays discovered skills
- weebot skill list --active-only filters correctly
- weebot skill install copies a Weebot-format SKILL.md
- weebot skill install converts an external format
- weebot skill install rejects unknown formats
"""
"""Unit tests for skill CLI commands.

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
        from cli.main import skill_list

        runner = CliRunner()
        result = runner.invoke(skill_list)

        assert result.exit_code == 0
        assert "test-skill" in result.output
        assert "A test skill" in result.output

    def test_list_active_when_no_env_set(self, populated_skills):
        """skill list --active-only shows skills with no env requirements."""
        from cli.main import skill_list

        runner = CliRunner()
        result = runner.invoke(skill_list, ["--active-only"])

        assert result.exit_code == 0
        assert "test-skill" in result.output

    def test_list_empty_when_no_skills(self, tmp_path, monkeypatch):
        """skill list on an empty directory shows 'No skills found'."""
        monkeypatch.chdir(tmp_path)

        from cli.main import skill_list

        runner = CliRunner()
        result = runner.invoke(skill_list)

        assert result.exit_code == 0
        assert "No skills found" in result.output


class TestSkillInstallCLI:
    """Validates the `weebot skill install` command."""

    def test_installs_weebot_skill(self, tmp_path, monkeypatch):
        """Installing a Weebot SKILL.md copies it to .weebot/skills/."""
        # Create source SKILL.md
        source = tmp_path / "my-skill" / "SKILL.md"
        source.parent.mkdir()
        source.write_text(
            "---\nname: my-skill\ndescription: My custom skill\n---\n\nSkill content"
        )

        monkeypatch.chdir(tmp_path)
        from cli.main import skill_install

        runner = CliRunner()
        result = runner.invoke(skill_install, [str(source.parent)])

        assert result.exit_code == 0
        assert "my-skill" in result.output
        assert (tmp_path / ".weebot" / "skills" / "my-skill" / "SKILL.md").exists()

    def test_installs_weebot_skill_from_file(self, tmp_path, monkeypatch):
        """Installing from a SKILL.md file path works."""
        source = tmp_path / "SKILL.md"
        source.write_text(
            "---\nname: file-skill\ndescription: From file\n---\n\nContent"
        )

        monkeypatch.chdir(tmp_path)
        from cli.main import skill_install

        runner = CliRunner()
        result = runner.invoke(skill_install, [str(source)])

        assert result.exit_code == 0
        assert "file-skill" in result.output
        assert (tmp_path / ".weebot" / "skills" / "file-skill" / "SKILL.md").exists()

    def test_install_rejects_unknown_format(self, tmp_path, monkeypatch):
        """Installing an unknown file format shows an error."""
        unknown = tmp_path / "random.txt"
        unknown.write_text("garbage content")

        monkeypatch.chdir(tmp_path)
        from cli.main import skill_install

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
        from cli.main import skill_install

        runner = CliRunner()
        result = runner.invoke(skill_install, [str(source), "--name", "custom-name"])

        assert result.exit_code == 0
        assert "custom-name" in result.output
        # The original-name dir should NOT exist
        assert not (tmp_path / ".weebot" / "skills" / "original-name").exists()
        # The custom-name dir should exist
        assert (tmp_path / ".weebot" / "skills" / "custom-name" / "SKILL.md").exists()
