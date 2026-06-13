"""AwesomeAgentSkillsAdapter — SkillIndexPort backed by heilcheng/awesome-agent-skills.

Parses the curated README index and fetches SKILL.md files directly from
each publisher's GitHub repository. Implements SkillIndexPort so the CLI
``skill update --source agentskills`` flow works without changes to the
update command logic.

Index resolution (two link types in the README):

  Type 1 — agent-skill.co proxy links:
    README link:  https://agent-skill.co/<owner>/skills/<slug>
    Primary URL:  https://raw.githubusercontent.com/<owner>/skills/main/skills/<slug>/SKILL.md
    Fallback URL: https://raw.githubusercontent.com/<owner>/skills/main/<slug>/SKILL.md

  Type 2 — direct GitHub links (exact repo name known):
    README link:  https://github.com/<owner>/<repo>/tree/main/skills/<slug>
    Download URL: https://raw.githubusercontent.com/<owner>/<repo>/main/skills/<slug>/SKILL.md

    Or bare repo links:
    README link:  https://github.com/<owner>/<repo>
    Download URL: https://raw.githubusercontent.com/<owner>/<repo>/main/skills/<slug>/SKILL.md
                  (slug derived from the display text)
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import httpx

from weebot.application.ports.skill_index_port import RemoteSkill, SkillIndexPort

logger = logging.getLogger(__name__)

# Type 1: agent-skill.co proxy links
# Matches:  - [display](https://agent-skill.co/<owner>/skills/<slug>) - description
_LINK_RE = re.compile(
    r"-\s*\[([^\]]+)\]\(https://agent-skill\.co/([^/]+)/skills/([^)]+)\)\s*[-–—]\s*(.+?)(?:\n|$)"
)

# Type 2: direct GitHub links with explicit path
# Matches:  - [display](https://github.com/<owner>/<repo>/tree/main/skills/<slug>) - description
_GITHUB_TREE_RE = re.compile(
    r"-\s*\[([^\]]+)\]\(https://github\.com/([^/]+)/([^/]+)/tree/main/skills/([^)]+)\)\s*[-–—]\s*(.+?)(?:\n|$)"
)

# Type 3: bare GitHub repo links (no /tree/main/skills/ path)
# Matches:  - [display](https://github.com/<owner>/<repo>) - description
_GITHUB_BARE_RE = re.compile(
    r"-\s*\[([^\]]+)\]\(https://github\.com/([^/]+)/([^)/]+)\)\s*[-–—]\s*(.+?)(?:\n|$)"
)

_HTTP_TIMEOUT = 15.0


class AwesomeAgentSkillsAdapter(SkillIndexPort):
    """SkillIndexPort implementation for the awesome-agent-skills curated index.

    Args:
        index_url: URL of the README.md to parse for skill links.
            Defaults to ``WeebotSettings.awesome_agent_skills_index_url``.
        http_client: Optional pre-configured httpx.AsyncClient.
    """

    def __init__(
        self,
        index_url: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        if index_url is None:
            from weebot.config.settings import WeebotSettings
            index_url = WeebotSettings().awesome_agent_skills_index_url
        self._index_url = index_url
        self._client = http_client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
        self._cached: list[RemoteSkill] = []

    # ── SkillIndexPort ───────────────────────────────────────────────

    async def fetch_index(self) -> list[RemoteSkill]:
        """Parse the README and return one RemoteSkill per indexed link.

        Returns an empty list on network failure (never raises).
        """
        try:
            resp = await self._client.get(self._index_url)
            resp.raise_for_status()
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.warning("awesome-agent-skills index fetch failed: %s", exc)
            return []

        skills: list[RemoteSkill] = []
        seen: set[str] = set()  # deduplicate by (owner, slug)

        # Type 1: agent-skill.co proxy links
        for m in _LINK_RE.finditer(resp.text):
            owner = m.group(2)
            slug = m.group(3).strip("/")
            description = m.group(4).strip()
            key = f"{owner}/{slug}"
            if key in seen:
                continue
            seen.add(key)

            primary_url = (
                f"https://raw.githubusercontent.com/{owner}/skills/main/skills/{slug}/SKILL.md"
            )
            skills.append(RemoteSkill(
                name=slug,
                version="latest",
                description=description,
                author=owner,
                download_url=primary_url,
                homepage=f"https://agent-skill.co/{owner}/skills/{slug}",
                tags=[owner, "awesome-agent-skills"],
            ))

        # Type 2: direct GitHub links with explicit /tree/main/skills/<slug> path
        for m in _GITHUB_TREE_RE.finditer(resp.text):
            owner = m.group(2)
            repo = m.group(3)
            slug = m.group(4).strip("/")
            description = m.group(5).strip()
            key = f"{owner}/{slug}"
            if key in seen:
                continue
            seen.add(key)

            download_url = (
                f"https://raw.githubusercontent.com/{owner}/{repo}/main/skills/{slug}/SKILL.md"
            )
            skills.append(RemoteSkill(
                name=slug,
                version="latest",
                description=description,
                author=owner,
                download_url=download_url,
                homepage=f"https://github.com/{owner}/{repo}/tree/main/skills/{slug}",
                tags=[owner, "awesome-agent-skills", "github-direct"],
            ))

        # Type 3: bare GitHub repo links (derive slug from display text)
        for m in _GITHUB_BARE_RE.finditer(resp.text):
            display = m.group(1)
            owner = m.group(2)
            repo = m.group(3)
            description = m.group(4).strip()
            # Derive slug from the display text's last component
            # e.g. "trycourier/courier-skills" → slug = "courier-skills"
            slug = display.split("/")[-1].strip() if "/" in display else repo
            key = f"{owner}/{slug}"
            if key in seen:
                continue
            seen.add(key)

            # For bare repo links, try the repo root (skills may be at
            # <repo>/skills/<slug>/SKILL.md or just <repo>/SKILL.md)
            download_url = (
                f"https://raw.githubusercontent.com/{owner}/{repo}/main/skills/{slug}/SKILL.md"
            )
            skills.append(RemoteSkill(
                name=slug,
                version="latest",
                description=description,
                author=owner,
                download_url=download_url,
                homepage=f"https://github.com/{owner}/{repo}",
                tags=[owner, "awesome-agent-skills", "github-direct"],
            ))

        self._cached = skills
        logger.info(
            "awesome-agent-skills index: %d skills parsed from README", len(skills)
        )
        return list(self._cached)

    async def search(self, query: str) -> list[RemoteSkill]:
        """Case-insensitive search over name, description, and author.

        Fetches the index on first call.
        """
        if not self._cached:
            await self.fetch_index()

        q = query.lower()
        scored: list[tuple[RemoteSkill, int]] = []
        for skill in self._cached:
            score = 0
            if q in skill.name.lower():
                score += 10
            if q in skill.description.lower():
                score += 5
            if q in skill.author.lower():
                score += 3
            if score > 0:
                scored.append((skill, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in scored]

    async def download(self, skill: RemoteSkill, target_dir: str) -> bool:
        """Download the raw SKILL.md to ``<target_dir>/SKILL.md``.

        Tries the primary URL from ``skill.download_url``, then a fallback
        path pattern before returning False.

        Unlike GitHubSkillIndexAdapter, there is no tarball or SHA-256
        verification — these are plain markdown files served over HTTPS from
        public GitHub repositories.

        Args:
            skill: RemoteSkill with a ``download_url`` pointing to a raw
                   GitHub SKILL.md.
            target_dir: Directory to write ``SKILL.md`` into.

        Returns:
            True on success, False on any failure.
        """
        urls_to_try = [skill.download_url]

        # Derive fallback URLs for different repo naming conventions.
        # Publishers use varied repo names: <owner>/skills (default),
        # <owner>/agent-skills, <owner>/<product>-skills, etc.
        if "/skills/main/skills/" in skill.download_url:
            # Fallback 1: <owner>/skills/main/<slug>/SKILL.md
            urls_to_try.append(
                skill.download_url.replace("/skills/main/skills/", "/skills/main/")
            )
            # Fallback 2: <owner>/agent-skills/main/skills/<slug>/SKILL.md
            urls_to_try.append(
                skill.download_url.replace("/skills/main/skills/", "/agent-skills/main/skills/")
            )
            # Fallback 3: <owner>/agent-skills/main/<slug>/SKILL.md
            urls_to_try.append(
                skill.download_url.replace("/skills/main/skills/", "/agent-skills/main/")
            )
        elif "/main/skills/" in skill.download_url:
            # Direct GitHub link — also try without skills/ prefix
            urls_to_try.append(
                skill.download_url.replace("/main/skills/", "/main/")
            )

        for url in urls_to_try:
            content = await self._fetch_raw(url)
            if content is not None:
                return self._write_skill_md(content, target_dir, skill.name)

        logger.warning(
            "Could not download SKILL.md for '%s' — tried %d URLs",
            skill.name, len(urls_to_try),
        )
        return False

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ── internals ────────────────────────────────────────────────────

    async def _fetch_raw(self, url: str) -> Optional[bytes]:
        """GET *url* and return content, or None on any error."""
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            return resp.content
        except (httpx.RequestError, httpx.HTTPStatusError):
            return None

    @staticmethod
    def _write_skill_md(content: bytes, target_dir: str, skill_name: str) -> bool:
        """Write *content* to ``<target_dir>/SKILL.md``.

        Validates that the downloaded content looks like a SKILL.md
        (starts with '---' frontmatter) before writing.
        """
        text = content.decode("utf-8-sig", errors="replace")
        if not text.lstrip().startswith("---"):
            logger.warning(
                "Skipping '%s' — downloaded content has no YAML frontmatter "
                "(not a valid SKILL.md)",
                skill_name,
            )
            return False

        out = Path(target_dir) / "SKILL.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
        logger.info("Installed '%s' → %s", skill_name, out)
        return True


# ── module-level helper (mirrors agentskills_index._parse_agentskills_skill) ──

def _parse_awesome_skill(raw: dict) -> RemoteSkill:
    """Convert a dict (for testing) into a RemoteSkill.

    Mirrors the pattern in skill_index_github._parse_skill so tests can
    construct RemoteSkill objects without importing the full adapter.
    """
    return RemoteSkill(
        name=raw.get("name", ""),
        version=raw.get("version", "latest"),
        description=raw.get("description", ""),
        author=raw.get("author", ""),
        download_url=raw.get("download_url", ""),
        homepage=raw.get("homepage", ""),
        tags=raw.get("tags", ["awesome-agent-skills"]),
        license=raw.get("license", ""),
    )
