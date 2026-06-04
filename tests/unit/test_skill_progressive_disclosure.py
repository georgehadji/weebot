"""Unit tests for Progressive Disclosure (Harness Enhancement H1).

Covers:
- Skill.get_reference() loads files lazily and caches
- Skill.get_reference() blocks path traversal
- Skill.list_references() returns available paths
- SkillRegistry discovers reference paths on load
- Skills without references/ work unchanged
"""
import pytest
from pathlib import Path


class TestProgressiveDisclosure:
    """Validates Skill.get_reference() and related methods."""

    @pytest.fixture
    def skill_with_references(self, tmp_path):
        """Create a skill directory with references/ subfolder."""
        from weebot.domain.models.skill import Skill

        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()

        # Main SKILL.md
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: Test\n---\n\nBody"
        )

        # Create references/
        ref_dir = skill_dir / "references"
        ref_dir.mkdir()
        (ref_dir / "aws.md").write_text("# AWS Configuration\n\nEC2 details...")
        (ref_dir / "gcp.md").write_text("# GCP Configuration\n\nGKE details...")

        # Nested subfolder
        nested = ref_dir / "deep"
        nested.mkdir()
        (nested / "nested.md").write_text("# Deep reference")

        skill = Skill(
            name="test-skill",
            description="Test",
            content="Body",
            source_path=str(skill_dir / "SKILL.md"),
        )
        # PrivateAttr must be set after construction
        skill._reference_paths = [
            "references/aws.md",
            "references/gcp.md",
            "references/deep/nested.md",
        ]
        return skill

    def test_get_reference_loads_content(self, skill_with_references):
        """First call loads content from disk; second returns cached."""
        skill = skill_with_references

        content = skill.get_reference("references/aws.md")
        assert content is not None
        assert "AWS" in content

        # Subsequent call returns cached — should not re-read
        skill.get_reference("references/aws.md")
        assert "AWS" in skill.references.get("references/aws.md", "")

    def test_get_reference_missing_file(self, skill_with_references):
        """Non-existent reference returns None."""
        skill = skill_with_references
        assert skill.get_reference("references/nonexistent.md") is None

    def test_get_reference_no_source_path(self):
        """Skill without source_path returns None for any reference."""
        from weebot.domain.models.skill import Skill

        skill = Skill(name="orphan", description="", content="")
        assert skill.get_reference("references/foo.md") is None

    def test_get_reference_blocks_traversal(self, skill_with_references):
        """Path containing .. returns None (traversal blocked)."""
        skill = skill_with_references
        assert skill.get_reference("../../etc/passwd") is None

    def test_get_reference_abs_path_blocked(self, skill_with_references):
        """Absolute path outside skill dir returns None."""
        skill = skill_with_references
        assert skill.get_reference("/etc/passwd") is None

    def test_list_references(self, skill_with_references):
        """list_references returns the discovered index."""
        skill = skill_with_references
        refs = skill.list_references()
        assert len(refs) == 3
        assert "references/aws.md" in refs
        assert "references/gcp.md" in refs
        assert "references/deep/nested.md" in refs

    def test_skill_without_references(self, tmp_path):
        """Skills without references/ directory work normally."""
        from weebot.domain.models.skill import Skill

        skill_dir = tmp_path / "simple-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: simple\ndescription: No refs\n---\n\nContent"
        )

        skill = Skill(
            name="simple",
            description="No refs",
            content="Content",
            source_path=str(skill_dir / "SKILL.md"),
        )

        assert skill.list_references() == []
        assert skill.get_reference("anything") is None


class TestSkillRegistryReferences:
    """Validates that SkillRegistry discovers reference paths."""

    def test_registry_discovers_references(self, tmp_path, monkeypatch):
        """When loading a skill with references/, _reference_paths is populated."""
        from weebot.application.skills.skill_registry import SkillRegistry

        # Create skill with references in a temp dir
        skills_root = tmp_path / ".weebot" / "skills"
        skill_dir = skills_root / "ref-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: ref-skill\ndescription: Has refs\n---\n\nBody"
        )
        ref_dir = skill_dir / "references"
        ref_dir.mkdir()
        (ref_dir / "guide.md").write_text("# Guide")

        monkeypatch.chdir(tmp_path)
        registry = SkillRegistry(search_paths=[skills_root])
        registry.load_all()

        skill = registry.get_skill("ref-skill")
        assert skill is not None
        assert "references/guide.md" in skill.list_references()

    def test_registry_no_references(self, tmp_path, monkeypatch):
        """Skills without references/ get an empty list."""
        from weebot.application.skills.skill_registry import SkillRegistry

        skills_root = tmp_path / ".weebot" / "skills"
        skill_dir = skills_root / "simple"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: simple\ndescription: No refs\n---\n\nContent"
        )

        monkeypatch.chdir(tmp_path)
        registry = SkillRegistry(search_paths=[skills_root])
        registry.load_all()

        skill = registry.get_skill("simple")
        assert skill is not None
        assert skill.list_references() == []
