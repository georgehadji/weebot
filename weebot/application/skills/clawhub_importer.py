"""ClawHub skill importer — parses awesome-openclaw-skills category files
and installs skills into weebot's registry.

Skills are listed in the repo's categories/*.md files as:
    [name](https://clawskills.sh/skills/<author>-<name>) - description

This module clones/reads the repo, parses all categories, and generates
minimal SKILL.md files from the available metadata.  Full skill bodies
can be fetched from ClawHub on demand via fetch_full_skill().
"""
from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ── Data models ──────────────────────────────────────────────────

@dataclass
class SkillEntry:
    name: str
    author: str
    slug: str           # author-name
    description: str
    category: str
    url: str
    installed: bool = False


@dataclass
class ImportResult:
    total_available: int = 0
    imported: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    installed: list[str] = field(default_factory=list)


# ── Repo parser ──────────────────────────────────────────────────

_REPO_URL = "https://github.com/VoltAgent/awesome-openclaw-skills.git"
_LINK_RE = re.compile(
    r'-\s*\[([^\]]+)]\((https://[^)]+)\)\s*[-–—]\s*(.+?)(?:\n|$)'
)


class ClawHubImporter:
    """Parse the awesome-openclaw-skills repo and import skills.

    Usage:
        importer = ClawHubImporter()
        importer.clone_or_update_repo()
        entries = importer.parse_all_categories()
        result = importer.import_category("security-and-passwords",
                                          install_dir=Path.home() / ".weebot/skills")
    """

    def __init__(self, repo_path: Optional[Path] = None):
        self._repo_path = repo_path

    @property
    def repo_path(self) -> Path:
        if self._repo_path is None:
            self._repo_path = Path(tempfile.gettempdir()) / "awesome-openclaw-skills"
        return self._repo_path

    def clone_or_update_repo(self) -> None:
        """Clone the repo if not present, otherwise pull latest."""
        if self.repo_path.exists():
            logger.info("Updating repo at %s", self.repo_path)
            subprocess.run(
                ["git", "-C", str(self.repo_path), "pull", "--ff-only"],
                capture_output=True, text=True,
            )
        else:
            logger.info("Cloning repo to %s", self.repo_path)
            subprocess.run(
                ["git", "clone", "--depth", "1", _REPO_URL, str(self.repo_path)],
                capture_output=True, text=True,
            )

    def parse_all_categories(self) -> list[SkillEntry]:
        """Parse every categories/*.md file and return all skill entries."""
        categories_dir = self.repo_path / "categories"
        if not categories_dir.exists():
            raise FileNotFoundError(
                f"Categories dir not found at {categories_dir}. "
                "Run clone_or_update_repo() first."
            )

        entries: list[SkillEntry] = []
        for cat_file in sorted(categories_dir.glob("*.md")):
            category = cat_file.stem.replace("-and-", " & ").replace("-", " ").title()
            entries.extend(self._parse_category_file(cat_file, category))

        logger.info("Parsed %d skills across %d categories",
                     len(entries),
                     len(list(categories_dir.glob("*.md"))))
        return entries

    def _parse_category_file(self, path: Path, category: str) -> list[SkillEntry]:
        """Parse a single categories/*.md file."""
        text = path.read_text(encoding="utf-8")
        entries: list[SkillEntry] = []

        for match in _LINK_RE.finditer(text):
            name = match.group(1).strip()
            url = match.group(2).strip()
            desc = match.group(3).strip()

            # Extract author-name slug from URL
            slug = self._extract_slug(url)
            if not slug:
                continue

            author = slug.split("-", 1)[0] if "-" in slug else "unknown"
            entries.append(SkillEntry(
                name=name,
                author=author,
                slug=slug,
                description=desc,
                category=category,
                url=url,
            ))

        return entries

    @staticmethod
    def _extract_slug(url: str) -> str:
        """Extract 'author-name' from a clawskills.sh or clawhub.ai URL."""
        # clawskills.sh/skills/author-name
        # clawhub.ai/author/name
        path = urlparse(url).path.strip("/")
        parts = path.split("/")
        if "skills" in parts:
            idx = parts.index("skills")
            return parts[idx + 1] if idx + 1 < len(parts) else ""
        # clawhub.ai format: /Author/name
        if len(parts) >= 2:
            return f"{parts[-2]}-{parts[-1]}".lower()
        return ""

    # ── Import ───────────────────────────────────────────────────

    def import_category(
        self,
        category_slug: str,
        install_dir: Path,
        top_n: int = 20,
    ) -> ImportResult:
        """Import the top N skills from a category.

        Args:
            category_slug: e.g. "security-and-passwords"
            install_dir: target directory (e.g. ~/.weebot/skills)
            top_n: max skills to import
        """
        cat_file = self.repo_path / "categories" / f"{category_slug}.md"
        if not cat_file.exists():
            return ImportResult(errors=[f"Category not found: {category_slug}"])

        category_name = category_slug.replace("-and-", " & ").replace("-", " ").title()
        entries = self._parse_category_file(cat_file, category_name)

        result = ImportResult(total_available=len(entries))

        for entry in entries[:top_n]:
            skill_dir = install_dir / entry.name
            if skill_dir.exists():
                result.skipped += 1
                continue

            try:
                self._generate_skill_file(skill_dir, entry)
                result.imported += 1
                result.installed.append(entry.name)
            except Exception as exc:
                result.errors.append(f"{entry.name}: {exc}")

        logger.info("Imported %d/%d skills from %s (skipped %d, errors %d)",
                     result.imported, result.total_available,
                     category_slug, result.skipped, len(result.errors))
        return result

    def _generate_skill_file(self, skill_dir: Path, entry: SkillEntry) -> None:
        """Write a minimal SKILL.md from the available metadata."""
        skill_dir.mkdir(parents=True, exist_ok=True)

        # Quote name to prevent YAML parsing numeric names (e.g. "12306") as int
        safe_name = entry.name.replace('"', '\\"')
        safe_desc = entry.description.replace('"', '\\"')
        content = (
            f'---\n'
            f'name: "{safe_name}"\n'
            f'description: "{safe_desc}"\n'
            f'license: MIT\n'
            f'source: {entry.url}\n'
            f'category: "{entry.category}"\n'
            f'author: "{entry.author}"\n'
            f'---\n'
            f'\n'
            f'# {entry.name}\n'
            f'\n'
            f'{entry.description}\n'
            f'\n'
            f'## Source\n'
            f'Full skill body available at: {entry.url}\n'
            f'\n'
            f'## Category\n'
            f'{entry.category}\n'
            f'\n'
            f'> This is a metadata-only import.'
            f'  Use `weebot skills clawhub fetch {entry.slug}`\n'
            f'> to download the complete skill body from ClawHub.\n'
        )
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

    # ── Full fetch (lazy) ────────────────────────────────────────

    def fetch_full_skill(self, slug: str, install_dir: Path) -> bool:
        """Download the complete SKILL.md from ClawHub for a specific skill."""
        # clawskills.sh redirects to clawhub.ai
        import urllib.request
        import json

        url = f"https://clawhub.ai/api/skills/{slug}"
        try:
            req = urllib.request.Request(url)
            req.add_header("Accept", "application/json")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                skill_dir = install_dir / data.get("name", slug)
                skill_dir.mkdir(parents=True, exist_ok=True)
                (skill_dir / "SKILL.md").write_text(
                    data.get("content", ""), encoding="utf-8"
                )
                return True
        except Exception as exc:
            logger.warning("Failed to fetch %s: %s", slug, exc)
            return False
