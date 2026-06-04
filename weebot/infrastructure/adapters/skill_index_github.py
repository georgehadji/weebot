"""GitHubSkillIndexAdapter — SkillHub index backed by a GitHub-hosted JSON file.

Fetches the SkillHub index from a configurable raw GitHub URL, searches it
client-side, and downloads skill packages with SHA-256 integrity verification.

The index is a single JSON file hosted at the URL configured in
``WeebotSettings.skillhub_index_url``.

Index format:
.. code-block:: json

    {
      "version": "1",
      "skills": [
        {
          "name": "web-research",
          "version": "1.2.0",
          "description": "...",
          "download_url": "https://.../skill.tar.gz",
          "sha256": "abc123..."
        }
      ]
    }
"""
from __future__ import annotations

import hashlib
import json
import logging
import tarfile
import tempfile
from pathlib import Path
from typing import Optional

import httpx

from weebot.application.ports.skill_index_port import RemoteSkill, SkillIndexPort

logger = logging.getLogger(__name__)

# Default timeout for HTTP requests to the SkillHub
_HTTP_TIMEOUT = 10.0
# Safety ceiling for skill tarballs — prevents OOM from malicious index entries
_MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


class GitHubSkillIndexAdapter(SkillIndexPort):
    """SkillHub index adapter using a GitHub-hosted JSON index.

    Args:
        index_url: URL of the remote index JSON.  Defaults to the
            ``skillhub_index_url`` setting from ``WeebotSettings``.
        http_client: Optional pre-configured ``httpx.AsyncClient``.
    """

    def __init__(
        self,
        index_url: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        if index_url is None:
            from weebot.config.settings import WeebotSettings

            settings = WeebotSettings()
            index_url = settings.skillhub_index_url
        self._index_url = index_url
        self._client = http_client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
        self._cached_skills: list[RemoteSkill] = []

    # ── index fetching ──────────────────────────────────────────────

    async def fetch_index(self) -> list[RemoteSkill]:
        """Fetch the full skill index from the remote endpoint.

        Returns:
            All remote skills, cached in-memory for subsequent
            ``search()`` calls.  Empty list on failure.
        """
        try:
            resp = await self._client.get(self._index_url)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("SkillHub index fetch failed (HTTP %d): %s", exc.response.status_code, exc)
            return []
        except (httpx.RequestError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("SkillHub index fetch failed: %s", exc)
            return []

        raw_skills = data.get("skills", [])
        self._cached_skills = [_parse_skill(s) for s in raw_skills]
        return list(self._cached_skills)

    # ── search ──────────────────────────────────────────────────────

    async def search(self, query: str) -> list[RemoteSkill]:
        """Search the cached index by name, tag, or description.

        If the index hasn't been fetched yet, fetches it first.
        Matching is case-insensitive substring.
        """
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

    # ── download ────────────────────────────────────────────────────

    async def download(self, skill: RemoteSkill, target_dir: str) -> bool:
        """Download, verify SHA-256, and extract a skill tarball.

        Args:
            skill: The remote skill to download.
            target_dir: Absolute path of the extraction target.

        Returns:
            ``True`` on success.
        """
        # Download (streamed with size limit to prevent OOM)
        try:
            async with self._client.stream("GET", skill.download_url) as resp:
                resp.raise_for_status()
                chunks = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > _MAX_DOWNLOAD_BYTES:
                        logger.warning(
                            "Download for %s exceeded %d bytes — aborting",
                            skill.name, _MAX_DOWNLOAD_BYTES,
                        )
                        return False
                    chunks.append(chunk)
                content = b"".join(chunks)
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.warning("Skill download failed: %s", exc)
            return False

        # SHA-256 verification
        if skill.sha256:
            actual = hashlib.sha256(content).hexdigest()
            if actual != skill.sha256:
                logger.warning(
                    "SHA-256 mismatch for %s: expected %s, got %s",
                    skill.name, skill.sha256, actual,
                )
                return False

        # Extract tarball
        try:
            with tempfile.TemporaryFile() as tmp:
                tmp.write(content)
                tmp.seek(0)
                with tarfile.open(fileobj=tmp, mode="r:gz") as tar:
                    tar.extractall(path=target_dir, filter="data")
        except (tarfile.TarError, OSError) as exc:
            logger.warning("Skill extraction failed: %s", exc)
            return False

        logger.info("Downloaded skill '%s' v%s to %s", skill.name, skill.version, target_dir)
        return True

    # ── lifecycle ───────────────────────────────────────────────────

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


# ── helper ──────────────────────────────────────────────────────────


def _parse_skill(raw: dict) -> RemoteSkill:
    """Convert a raw JSON dict into a RemoteSkill dataclass."""
    return RemoteSkill(
        name=raw.get("name", ""),
        version=raw.get("version", "0.0.0"),
        description=raw.get("description", ""),
        author=raw.get("author", ""),
        download_url=raw.get("download_url", ""),
        sha256=raw.get("sha256", ""),
        homepage=raw.get("homepage", ""),
        tags=raw.get("tags", []),
        min_weebot_version=raw.get("min_weebot_version", "0.0.0"),
        dependencies=raw.get("dependencies", []),
        license=raw.get("license", ""),
    )
