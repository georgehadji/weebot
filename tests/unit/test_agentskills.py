"""Unit tests for agentskills.io Compatibility (Hermes M9)."""
import pytest


class TestAgentskillsAdapter:
    """Validates AgentskillsIndexAdapter."""

    def test_parse_agentskills_skill(self):
        from weebot.infrastructure.adapters.agentskills_index import (
            _parse_agentskills_skill,
        )

        raw = {
            "name": "web-research",
            "version": "1.2.0",
            "description": "Multi-source web research",
            "author": "community",
            "download_url": "https://agentskills.io/skills/web-research.tar.gz",
            "sha256": "abc123",
            "tags": ["research", "web"],
        }
        skill = _parse_agentskills_skill(raw)
        assert skill.name == "web-research"
        assert skill.version == "1.2.0"
        assert "research" in skill.tags
