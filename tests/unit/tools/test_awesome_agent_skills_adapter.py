"""Unit tests for AwesomeAgentSkillsAdapter (Fix 3).

Covers:
- fetch_index — parses README links, handles HTTP errors
- search — by name, description, author, case insensitive
- download — writes SKILL.md, uses fallback URL, validates frontmatter
- Settings — new awesome_agent_skills_index_url in WeebotSettings
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

# ── Sample README snippets ──────────────────────────────────────────

SAMPLE_README = """
## Official Skills

- [anthropics/docx](https://agent-skill.co/anthropics/skills/docx) - Create Word documents
- [getsentry/code-review](https://agent-skill.co/getsentry/skills/code-review) - Perform code reviews

## Community Skills

- [trailofbits/security-scan](https://agent-skill.co/trailofbits/skills/security-scan) - Security audit tool
"""

SAMPLE_README_NO_MATCHES = """
## Skills

This README has no agent-skill.co links.
Just a standard markdown file.
"""


class TestAwesomeAgentSkillsAdapter:
    """Validates AwesomeAgentSkillsAdapter core logic."""

    @pytest.fixture
    def adapter(self):
        from weebot.infrastructure.adapters.awesome_agent_skills_adapter import (
            AwesomeAgentSkillsAdapter,
        )

        return AwesomeAgentSkillsAdapter(
            index_url="https://example.com/README.md",
            http_client=MagicMock(),
        )

    # ── fetch_index ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_fetch_index_parses_readme_links(self, adapter):
        """Successful fetch returns parsed RemoteSkill list from README."""
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_README
        adapter._client.get = AsyncMock(return_value=mock_resp)

        skills = await adapter.fetch_index()
        assert len(skills) == 3

        # First skill: anthropics/docx
        assert skills[0].name == "docx"
        assert skills[0].author == "anthropics"
        assert skills[0].description == "Create Word documents"
        assert "anthropics" in skills[0].download_url
        assert "anthropics" in skills[0].homepage

        # Second skill: getsentry/code-review
        assert skills[1].name == "code-review"
        assert skills[1].author == "getsentry"
        assert skills[1].description == "Perform code reviews"

        # Third skill: trailofbits/security-scan
        assert skills[2].name == "security-scan"
        assert skills[2].author == "trailofbits"

    @pytest.mark.asyncio
    async def test_fetch_index_http_error_returns_empty(self, adapter):
        """HTTP 404 returns empty list (graceful degradation)."""
        from httpx import HTTPStatusError

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.raise_for_status.side_effect = HTTPStatusError(
            "Not found", request=MagicMock(), response=mock_resp,
        )

        adapter._client.get = AsyncMock(return_value=mock_resp)

        skills = await adapter.fetch_index()
        assert skills == []

    @pytest.mark.asyncio
    async def test_fetch_index_network_error_returns_empty(self, adapter):
        """Network error returns empty list (graceful degradation)."""
        from httpx import RequestError

        adapter._client.get = AsyncMock(
            side_effect=RequestError("DNS failed"),
        )

        skills = await adapter.fetch_index()
        assert skills == []

    @pytest.mark.asyncio
    async def test_fetch_index_no_agent_skill_links(self, adapter):
        """README with no matching links returns empty list."""
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_README_NO_MATCHES
        adapter._client.get = AsyncMock(return_value=mock_resp)

        skills = await adapter.fetch_index()
        assert skills == []

    # ── search ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_search_by_name(self, adapter):
        """Search by name finds the matching skill."""
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_README
        adapter._client.get = AsyncMock(return_value=mock_resp)

        results = await adapter.search("docx")
        assert len(results) == 1
        assert results[0].name == "docx"

    @pytest.mark.asyncio
    async def test_search_by_description(self, adapter):
        """Search by description substring finds matching skills."""
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_README
        adapter._client.get = AsyncMock(return_value=mock_resp)

        results = await adapter.search("code reviews")
        assert len(results) >= 1
        assert results[0].name == "code-review"

    @pytest.mark.asyncio
    async def test_search_by_author(self, adapter):
        """Search by author/owner finds matching skills."""
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_README
        adapter._client.get = AsyncMock(return_value=mock_resp)

        results = await adapter.search("trailofbits")
        assert len(results) == 1
        assert results[0].name == "security-scan"

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self, adapter):
        """Search is case-insensitive."""
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_README
        adapter._client.get = AsyncMock(return_value=mock_resp)

        results = await adapter.search("DOCX")
        assert len(results) == 1
        assert results[0].name == "docx"

    @pytest.mark.asyncio
    async def test_search_no_match_returns_empty(self, adapter):
        """No match returns empty list."""
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_README
        adapter._client.get = AsyncMock(return_value=mock_resp)

        results = await adapter.search("nonexistent")
        assert results == []

    # ── download ────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_download_writes_skill_md(self, adapter, tmp_path):
        """Download with valid SKILL.md content writes to target dir."""
        mock_resp = MagicMock()
        mock_resp.content = b"---\nname: test-skill\ndescription: x\n---\nHello"
        adapter._client.get = AsyncMock(return_value=mock_resp)

        from weebot.infrastructure.adapters.awesome_agent_skills_adapter import (
            _parse_awesome_skill,
        )

        skill = _parse_awesome_skill({
            "name": "test-skill",
            "download_url": "https://raw.githubusercontent.com/test/skills/main/skills/test-skill/SKILL.md",
        })

        result = await adapter.download(skill, str(tmp_path))
        assert result is True
        assert (tmp_path / "SKILL.md").exists()
        assert "test-skill" in (tmp_path / "SKILL.md").read_text()

    @pytest.mark.asyncio
    async def test_download_uses_fallback_url(self, adapter, tmp_path):
        """Primary URL 404, fallback URL 200 → download succeeds."""
        from httpx import HTTPStatusError

        # Primary URL fails with 404
        primary_resp = MagicMock()
        primary_resp.status_code = 404
        primary_resp.raise_for_status.side_effect = HTTPStatusError(
            "Not found", request=MagicMock(), response=primary_resp,
        )

        # Fallback URL succeeds
        fallback_resp = MagicMock()
        fallback_resp.content = b"---\nname: fallback-skill\ndescription: x\n---\nContent"

        adapter._client.get = AsyncMock(side_effect=[
            primary_resp,       # primary URL → 404
            fallback_resp,      # fallback URL → 200
        ])

        from weebot.infrastructure.adapters.awesome_agent_skills_adapter import (
            _parse_awesome_skill,
        )

        skill = _parse_awesome_skill({
            "name": "fallback-skill",
            "download_url": (
                "https://raw.githubusercontent.com/getsentry/skills/main/skills/"
                "fallback-skill/SKILL.md"
            ),
        })

        result = await adapter.download(skill, str(tmp_path))
        assert result is True
        assert (tmp_path / "SKILL.md").exists()

    @pytest.mark.asyncio
    async def test_download_no_frontmatter_returns_false(self, adapter, tmp_path):
        """Content without YAML frontmatter (no '---') returns False."""
        mock_resp = MagicMock()
        mock_resp.content = b"This is plain text, not a SKILL.md"
        adapter._client.get = AsyncMock(return_value=mock_resp)

        from weebot.infrastructure.adapters.awesome_agent_skills_adapter import (
            _parse_awesome_skill,
        )

        skill = _parse_awesome_skill({
            "name": "bad-skill",
            "download_url": "https://example.com/bad/SKILL.md",
        })

        result = await adapter.download(skill, str(tmp_path))
        assert result is False
        # No file should have been written
        assert not (tmp_path / "SKILL.md").exists()

    @pytest.mark.asyncio
    async def test_download_both_urls_fail_returns_false(self, adapter, tmp_path):
        """Both primary and fallback URLs 404 → returns False."""
        from httpx import HTTPStatusError

        def _make_error():
            resp = MagicMock()
            resp.status_code = 404
            resp.raise_for_status.side_effect = HTTPStatusError(
                "Not found", request=MagicMock(), response=resp,
            )
            return resp

        adapter._client.get = AsyncMock(side_effect=[
            _make_error(),  # primary → 404
            _make_error(),  # fallback → 404
        ])

        from weebot.infrastructure.adapters.awesome_agent_skills_adapter import (
            _parse_awesome_skill,
        )

        skill = _parse_awesome_skill({
            "name": "missing-skill",
            "download_url": "https://example.com/missing/SKILL.md",
        })

        result = await adapter.download(skill, str(tmp_path))
        assert result is False
        assert not (tmp_path / "SKILL.md").exists()


# ── _parse_awesome_skill helper ────────────────────────────────────


class TestParseAwesomeSkill:
    """Validates the _parse_awesome_skill helper function."""

    def test_parse_awesome_skill_fields(self):
        """All fields populated correctly."""
        from weebot.infrastructure.adapters.awesome_agent_skills_adapter import (
            _parse_awesome_skill,
        )

        raw = {
            "name": "web-research",
            "version": "1.2.0",
            "description": "Multi-source web research",
            "author": "community",
            "download_url": "https://example.com/skills/web-research/SKILL.md",
            "homepage": "https://agent-skill.co/community/skills/web-research",
            "tags": ["research", "web"],
            "license": "MIT",
        }
        skill = _parse_awesome_skill(raw)
        assert skill.name == "web-research"
        assert skill.version == "1.2.0"
        assert skill.author == "community"
        assert "research" in skill.tags
        assert skill.license == "MIT"

    def test_parse_awesome_skill_defaults(self):
        """Missing fields get sensible defaults."""
        from weebot.infrastructure.adapters.awesome_agent_skills_adapter import (
            _parse_awesome_skill,
        )

        skill = _parse_awesome_skill({"name": "minimal"})
        assert skill.name == "minimal"
        assert skill.version == "latest"
        assert skill.description == ""
        assert skill.author == ""
        assert skill.tags == ["awesome-agent-skills"]


# ── Settings ────────────────────────────────────────────────────────


class TestAwesomeAgentSkillsSettings:
    """Validates awesome_agent_skills_index_url in WeebotSettings."""

    def test_awesome_index_url_in_settings(self, with_openai_key):
        """WeebotSettings has the awesome_agent_skills_index_url field."""
        from weebot.config.settings import WeebotSettings

        settings = WeebotSettings()
        assert hasattr(settings, "awesome_agent_skills_index_url")
        assert "heilcheng" in settings.awesome_agent_skills_index_url
        assert settings.awesome_agent_skills_index_url.endswith(".md")

    def test_skillhub_url_not_affected(self, with_openai_key):
        """New setting does not change the existing skillhub_index_url."""
        from weebot.config.settings import WeebotSettings

        settings = WeebotSettings()
        assert "weebot-community" in settings.skillhub_index_url
        assert settings.skillhub_index_url.endswith(".json")
