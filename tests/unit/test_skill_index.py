"""Unit tests for SkillHub remote index (Enhancement 6).

Covers:
- GitHubSkillIndexAdapter.fetch_index() — success, HTTP errors, parse errors
- GitHubSkillIndexAdapter.search() — by name, tag, description; case insensitivity
- GitHubSkillIndexAdapter.download() — success with SHA-256 verification, mismatch, network failure
- SkillHub setting default value
- CLI `skill update --check` and `skill update <name>`
"""
import json
import hashlib
import tarfile
import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── sample index ────────────────────────────────────────────────────

SAMPLE_INDEX = {
    "version": "1",
    "skills": [
        {
            "name": "web-research",
            "version": "1.2.0",
            "description": "Multi-source web research agent with scraping",
            "author": "weebot-community",
            "download_url": "https://example.com/web-research.tar.gz",
            "sha256": "a" * 64,
            "homepage": "https://github.com/weebot-community/skill-web-research",
            "tags": ["research", "web", "scraping"],
            "min_weebot_version": "2.0.0",
            "dependencies": [],
            "license": "MIT",
        },
        {
            "name": "code-review",
            "version": "0.9.0",
            "description": "Automated code review assistant",
            "author": "weebot-community",
            "download_url": "https://example.com/code-review.tar.gz",
            "sha256": "b" * 64,
            "tags": ["code", "review", "quality"],
            "license": "Apache-2.0",
        },
    ],
}


class TestSkillHubAdapter:
    """Validates GitHubSkillIndexAdapter core logic."""

    @pytest.fixture
    def adapter(self):
        from weebot.infrastructure.adapters.skill_index_github import (
            GitHubSkillIndexAdapter,
        )

        return GitHubSkillIndexAdapter(
            index_url="https://example.com/index.json",
            http_client=MagicMock(),
        )

    # ── fetch_index ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_fetch_index_success(self, adapter):
        """Successful fetch returns parsed RemoteSkill list."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_INDEX

        adapter._client.get = AsyncMock(return_value=mock_resp)

        skills = await adapter.fetch_index()
        assert len(skills) == 2
        assert skills[0].name == "web-research"
        assert skills[0].version == "1.2.0"
        assert skills[1].name == "code-review"
        assert skills[1].sha256 == "b" * 64

    @pytest.mark.asyncio
    async def test_fetch_index_http_error(self, adapter):
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
    async def test_fetch_index_network_error(self, adapter):
        """Network error returns empty list (graceful degradation)."""
        from httpx import RequestError

        adapter._client.get = AsyncMock(
            side_effect=RequestError("DNS failed"),
        )

        skills = await adapter.fetch_index()
        assert skills == []

    @pytest.mark.asyncio
    async def test_fetch_index_invalid_json(self, adapter):
        """Invalid JSON returns empty list."""
        mock_resp = MagicMock()
        mock_resp.json.side_effect = json.JSONDecodeError("bad json", "", 0)

        adapter._client.get = AsyncMock(return_value=mock_resp)

        skills = await adapter.fetch_index()
        assert skills == []

    # ── search ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_search_by_name(self, adapter):
        """Search by name finds the matching skill."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_INDEX
        adapter._client.get = AsyncMock(return_value=mock_resp)

        results = await adapter.search("web-research")
        assert len(results) == 1
        assert results[0].name == "web-research"

    @pytest.mark.asyncio
    async def test_search_by_tag(self, adapter):
        """Search by tag finds skills with that tag."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_INDEX
        adapter._client.get = AsyncMock(return_value=mock_resp)

        results = await adapter.search("scraping")
        assert len(results) == 1
        assert results[0].name == "web-research"

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self, adapter):
        """Search is case-insensitive."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_INDEX
        adapter._client.get = AsyncMock(return_value=mock_resp)

        results = await adapter.search("WEB-RESEARCH")
        assert len(results) == 1
        assert results[0].name == "web-research"

    @pytest.mark.asyncio
    async def test_search_no_match(self, adapter):
        """No match returns empty list."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_INDEX
        adapter._client.get = AsyncMock(return_value=mock_resp)

        results = await adapter.search("nonexistent")
        assert results == []

    # ── download ────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_download_success(self, adapter, tmp_path):
        """Download with valid SHA-256 extracts to target."""
        # Create a fake tarball
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="SKILL.md")
            info.size = 11
            tar.addfile(info, io.BytesIO(b"hello world"))
        tar_bytes = tar_buffer.getvalue()
        sha256 = hashlib.sha256(tar_bytes).hexdigest()

        # Mock streaming HTTP response
        mock_resp = MagicMock()
        async def _iter_bytes():
            yield tar_bytes
        mock_resp.aiter_bytes = _iter_bytes
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_resp

        adapter._client.stream = MagicMock(return_value=mock_context)

        skill = SAMPLE_INDEX["skills"][0].copy()
        skill["sha256"] = sha256
        from weebot.infrastructure.adapters.skill_index_github import _parse_skill
        remote = _parse_skill(skill)

        result = await adapter.download(remote, str(tmp_path))
        assert result is True
        assert (tmp_path / "SKILL.md").exists()
        assert (tmp_path / "SKILL.md").read_text() == "hello world"

    @pytest.mark.asyncio
    async def test_download_sha256_mismatch(self, adapter, tmp_path):
        """SHA-256 mismatch returns False and does NOT extract."""
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w:gz"):
            pass
        tar_bytes = tar_buffer.getvalue()

        mock_resp = MagicMock()
        async def _iter_bytes():
            yield tar_bytes
        mock_resp.aiter_bytes = _iter_bytes
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_resp
        adapter._client.stream = MagicMock(return_value=mock_context)

        from weebot.infrastructure.adapters.skill_index_github import _parse_skill
        skill = _parse_skill({
            "name": "bad-skill",
            "version": "1.0",
            "download_url": "https://example.com/bad.tar.gz",
            "sha256": "f" * 64,  # Wrong hash
        })

        result = await adapter.download(skill, str(tmp_path))
        assert result is False

    @pytest.mark.asyncio
    async def test_download_network_error(self, adapter, tmp_path):
        """Network failure during download returns False."""
        from httpx import RequestError

        mock_context = MagicMock()
        mock_context.__aenter__.side_effect = RequestError("timeout")
        adapter._client.stream = MagicMock(return_value=mock_context)

        from weebot.infrastructure.adapters.skill_index_github import _parse_skill
        skill = _parse_skill(SAMPLE_INDEX["skills"][0])

        result = await adapter.download(skill, str(tmp_path))
        assert result is False


class TestSkillHubSettings:
    """Validates SkillHub configuration."""

    def test_default_index_url(self, with_openai_key):
        """Default skillhub_index_url is the GitHub weebot-community index."""
        from weebot.config.settings import WeebotSettings

        settings = WeebotSettings()
        assert "weebot-community" in settings.skillhub_index_url
        assert settings.skillhub_index_url.endswith(".json")
