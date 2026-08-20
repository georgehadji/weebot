"""Unit tests for Ponytail built-in skills."""

from __future__ import annotations

import pytest

from weebot.application.skills.skill_registry import SkillRegistry


@pytest.fixture
def registry() -> SkillRegistry:
    """Load the built-in skill registry."""
    reg = SkillRegistry()
    reg.load_all()
    return reg


@pytest.mark.parametrize(
    "name,expected_phrase",
    [
        ("ponytail", "The ladder"),
        ("ponytail", "ponytail:"),
        ("ponytail-review", "net: -"),
        ("ponytail-audit", "repo-wide"),
        ("ponytail-help", "Ponytail Help"),
    ],
)
def test_ponytail_skills_load(registry: SkillRegistry, name: str, expected_phrase: str) -> None:
    """Each Ponytail skill parses and contains its signature content."""
    skill = registry.get(name)
    assert skill is not None, f"Skill '{name}' not found"
    assert skill.name == name
    assert skill.description
    assert skill.content
    assert expected_phrase in skill.content, f"Missing '{expected_phrase}' in {name}"


def test_ponytail_skill_system_prompt_extension(registry: SkillRegistry) -> None:
    """The ponytail skill produces a non-empty system prompt extension."""
    skill = registry.get("ponytail")
    assert skill is not None
    extension = skill.to_system_prompt_extension()
    assert "Ponytail" in extension
    assert "The ladder" in extension


def test_ponytail_help_skill_is_reference_only(registry: SkillRegistry) -> None:
    """ponytail-help is a reference card and does not claim to mutate state."""
    skill = registry.get("ponytail-help")
    assert skill is not None
    assert "reference card" in skill.content.lower()
    assert "do NOT change mode" in skill.content
