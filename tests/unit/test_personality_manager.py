"""Tests for PersonalityManager XML-scoped prompt parsing.

Covers:
- XML section parsing from WEEBOT_CORE.md
- Role-based section filtering via RoleSectionMapping
- Empty file, missing file, unknown role, malformed XML
- Hot-reload (refresh())
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from weebot.core.personality_manager import PersonalityManager
from weebot.domain.models.personality import RoleSectionMapping


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def xml_core_content() -> str:
    return """# Weebot Core — Identity & Safeguards

<identity>
You are Weebot, an autonomous agent.
Name: Weebot
Role: Autonomous agent orchestrator
</identity>

<invariant_rules>
1. **Workspace Isolation** — All file ops must stay within WEEBOT_WORKSPACE.
2. **Safety First** — Never bypass BashGuard.
</invariant_rules>

<operating_principles>
- Plan first — Break complex tasks into steps.
- Fail gracefully — Use the plan-update mechanism.
</operating_principles>

<response_style>
- Be concise but complete.
- Never fabricate information.
</response_style>
"""


@pytest.fixture
def core_file(tmp_path: Path, xml_core_content: str) -> Path:
    path = tmp_path / "WEEBOT_CORE.md"
    path.write_text(xml_core_content, encoding="utf-8")
    return path


@pytest.fixture
def empty_core_file(tmp_path: Path) -> Path:
    path = tmp_path / "WEEBOT_CORE.md"
    path.write_text("", encoding="utf-8")
    return path


# ── Section Parsing Tests ─────────────────────────────────────────────

class TestParseXmlSections:
    """Test the static XML section parser."""

    def test_parses_all_sections(self, xml_core_content: str):
        sections = PersonalityManager._parse_xml_sections(xml_core_content)
        assert set(sections.keys()) == {"identity", "invariant_rules", "operating_principles", "response_style"}

    def test_strips_xml_tags_from_content(self, xml_core_content: str):
        sections = PersonalityManager._parse_xml_sections(xml_core_content)
        assert "<identity>" not in sections["identity"]
        assert "</identity>" not in sections["identity"]
        assert "You are Weebot" in sections["identity"]

    def test_preserves_markdown_content(self, xml_core_content: str):
        sections = PersonalityManager._parse_xml_sections(xml_core_content)
        assert "**Workspace Isolation**" in sections["invariant_rules"]
        assert "- Plan first" in sections["operating_principles"]

    def test_empty_content_returns_empty_dict(self):
        sections = PersonalityManager._parse_xml_sections("")
        assert sections == {}

    def test_no_xml_tags_returns_empty_dict(self):
        sections = PersonalityManager._parse_xml_sections("# Just markdown\nNo XML here.")
        assert sections == {}

    def test_malformed_xml_graceful(self):
        raw = "<identity>No closing tag here"
        sections = PersonalityManager._parse_xml_sections(raw)
        assert sections == {}


# ── PersonalityManager Tests ─────────────────────────────────────────

class TestPersonalityManager:
    """Test the PersonalityManager with XML-scoped prompts."""

    def test_loads_sections_from_file(self, core_file: Path):
        pm = PersonalityManager(core_path=core_file)
        assert pm.loaded
        assert pm.section_names == ["identity", "invariant_rules", "operating_principles", "response_style"]

    def test_missing_file_logs_warning_and_returns_empty(self):
        pm = PersonalityManager(core_path=Path("/nonexistent/WEEBOT_CORE.md"))
        assert not pm.loaded
        assert pm.content == ""

    def test_empty_file_returns_not_loaded(self, empty_core_file: Path):
        pm = PersonalityManager(core_path=empty_core_file)
        assert not pm.loaded

    def test_get_system_prompt_without_role_includes_all_sections(self, core_file: Path):
        pm = PersonalityManager(core_path=core_file)
        prompt = pm.get_system_prompt()
        assert "## Core Identity & Safeguards" in prompt
        assert "You are Weebot" in prompt
        assert "**Workspace Isolation**" in prompt
        assert "- Plan first" in prompt
        assert "Be concise but complete" in prompt

    def test_get_system_prompt_empty_when_not_loaded(self):
        pm = PersonalityManager(core_path=Path("/nonexistent/WEEBOT_CORE.md"))
        assert pm.get_system_prompt() == ""

    def test_get_system_prompt_with_role_filters_sections(self, core_file: Path):
        pm = PersonalityManager(core_path=core_file)
        prompt = pm.get_system_prompt(role="automation")
        assert "## Core Identity & Safeguards (role: automation)" in prompt
        assert "You are Weebot" in prompt  # identity included
        assert "**Workspace Isolation**" in prompt  # invariant_rules included
        assert "- Plan first" not in prompt  # operating_principles excluded
        assert "Be concise but complete" not in prompt  # response_style excluded

    def test_get_system_prompt_admin_role_includes_all(self, core_file: Path):
        pm = PersonalityManager(core_path=core_file)
        prompt = pm.get_system_prompt(role="admin")
        assert "You are Weebot" in prompt
        assert "**Workspace Isolation**" in prompt
        assert "- Plan first" in prompt
        assert "Be concise but complete" in prompt

    def test_get_system_prompt_researcher_excludes_response_style(self, core_file: Path):
        pm = PersonalityManager(core_path=core_file)
        prompt = pm.get_system_prompt(role="researcher")
        assert "You are Weebot" in prompt
        assert "**Workspace Isolation**" in prompt
        assert "- Plan first" in prompt
        assert "Be concise but complete" not in prompt

    def test_get_system_prompt_unknown_role_falls_back_to_all(self, core_file: Path):
        pm = PersonalityManager(core_path=core_file)
        prompt = pm.get_system_prompt(role="nonexistent_role")
        assert "You are Weebot" in prompt
        assert "**Workspace Isolation**" in prompt

    def test_refresh_reloads_file(self, tmp_path: Path):
        path = tmp_path / "WEEBOT_CORE.md"
        path.write_text("<identity>Initial</identity>", encoding="utf-8")
        pm = PersonalityManager(core_path=path)
        assert pm.content == "Initial"

        # Modify the file
        path.write_text("<identity>Updated</identity>", encoding="utf-8")
        pm.refresh()
        assert pm.content == "Updated"

    def test_content_property_concatenates_all_sections(self, core_file: Path):
        pm = PersonalityManager(core_path=core_file)
        content = pm.content
        # Should contain content from all sections, with no XML tags
        assert "<identity>" not in content
        assert "You are Weebot" in content
        assert "Never fabricate information" in content


# ── RoleSectionMapping Tests ──────────────────────────────────────────

class TestRoleSectionMapping:
    """Test the role-to-section mapping logic."""

    def test_admin_gets_all_sections(self):
        sections = RoleSectionMapping.sections_for_role("admin")
        assert sections == [
            "identity",
            "invariant_rules",
            "operating_principles",
            "response_style",
            "web_3d_motion",
            "youtube_downloads",
            "vision_osworld",
        ]

    def test_researcher_gets_subset(self):
        sections = RoleSectionMapping.sections_for_role("researcher")
        assert "response_style" not in sections
        assert "identity" in sections
        assert "invariant_rules" in sections

    def test_automation_gets_minimal(self):
        sections = RoleSectionMapping.sections_for_role("automation")
        assert sections == [
            "identity",
            "invariant_rules",
            "web_3d_motion",
            "youtube_downloads",
            "vision_osworld",
        ]

    def test_unknown_role_falls_back(self):
        sections = RoleSectionMapping.sections_for_role("unknown_role")
        # Falls back to all known sections
        assert "identity" in sections
        assert "invariant_rules" in sections
        assert "operating_principles" in sections
        assert "response_style" in sections

    def test_all_section_tags_returns_all(self):
        tags = RoleSectionMapping.all_section_tags()
        assert "identity" in tags
        assert "invariant_rules" in tags
        assert "operating_principles" in tags
        assert "response_style" in tags
