"""AgentskillsIndexAdapter — agentskills.io open standard index adapter.

Parses the agentskills.io index format (https://agentskills.io) in
addition to the existing weebot SkillHub format.

The agentskills.io format:
.. code-block:: json

    {
      "skills": [
        {
          "name": "web-research",
          "version": "1.2.0",
          "description": "...",
          "author": "weebot-community",
          "download_url": "https://agentskills.io/skills/...",
          "sha256": "...",
          "tags": ["research", "web"],
          "compatibility": {
            "platforms": ["macos", "linux"],
            "min_agent_version": "0.0.0"
          }
        }
      ]
    }
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

from weebot.application.ports.skill_index_port import RemoteSkill, SkillIndexPort
from weebot.infrastructure.adapters.skill_index_github import _parse_skill

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 10.0
_MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024


class AgentskillsIndexAdapter(SkillIndexPort):
    """SkillHub index adapter for agentskills.io compatible indexes.

    Args:
        index_url: URL of the agentskills.io JSON index.
        http_client: Optional pre-configured ``httpx.AsyncClient``.
    """

    def __init__(
        self,
        index_url: str = "https://agentskills.io/api/v1/index.json",
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._index_url = index_url
        self._client = http_client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
        self._cached_skills: list[RemoteSkill] = []

    async def fetch_index(self) -> list[RemoteSkill]:
        """Fetch skill index from an agentskills.io compatible endpoint."""
        try:
            resp = await self._client.get(self._index_url)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError, json.JSONDecodeError) as exc:
            logger.warning("agentskills.io index fetch failed: %s", exc)
            return []

        raw_skills = data.get("skills", [])
        self._cached_skills = [_parse_agentskills_skill(s) for s in raw_skills]
        return list(self._cached_skills)

    async def search(self, query: str) -> list[RemoteSkill]:
        """Search the cached index."""
        if not self._cached_skills:
            await self.fetch_index()

        q = query.lower()
        results: list[tuple[RemoteSkill, int]] = []
        for skill in self._cached_skills:
            score = 0
            if q in skill.name.lower():
                score += 10
            if q in skill.description.lower():
                score += 5
            for tag in skill.tags:
                if q in tag.lower():
                    score += 3
            if score > 0:
                results.append((skill, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return [r[0] for r in results]

    async def download(self, skill: RemoteSkill, target_dir: str) -> bool:
        """Download and install a skill.

        Reuses the existing SHA-256 verified download from the
        GitHubSkillIndexAdapter pattern.
        """
        import hashlib
        import tarfile
        import tempfile
        from pathlib import Path

        try:
            resp = await self._client.get(skill.download_url)
            resp.raise_for_status()
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.warning("Skill download failed: %s", exc)
            return False

        content = resp.content

        if skill.sha256:
            actual = hashlib.sha256(content).hexdigest()
            if actual != skill.sha256:
                logger.warning("SHA-256 mismatch for %s", skill.name)
                return False

        try:
            with tempfile.TemporaryFile() as tmp:
                tmp.write(content)
                tmp.seek(0)
                with tarfile.open(fileobj=tmp, mode="r:gz") as tar:
                    tar.extractall(path=target_dir, filter="data")
        except (tarfile.TarError, OSError) as exc:
            logger.warning("Skill extraction failed: %s", exc)
            return False

        return True

    async def close(self) -> None:
        await self._client.aclose()


def _parse_agentskills_skill(raw: dict) -> RemoteSkill:
    """Parse an agentskills.io-format skill entry."""
    compat = raw.get("compatibility", {})
    return RemoteSkill(
        name=raw.get("name", ""),
        version=raw.get("version", "0.0.0"),
        description=raw.get("description", ""),
        author=raw.get("author", ""),
        download_url=raw.get("download_url", ""),
        sha256=raw.get("sha256", ""),
        homepage=raw.get("homepage", ""),
        tags=raw.get("tags", []),
        license=raw.get("license", ""),
    )
