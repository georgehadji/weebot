"""Bulk download skills from heilcheng/awesome-agent-skills.

Fetches the full index, attempts to download every skill, and reports
which succeeded vs failed (with the URLs tried).

Usage:
    python scripts/download_awesome_skills.py [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from weebot.infrastructure.adapters.awesome_agent_skills_adapter import (
    AwesomeAgentSkillsAdapter,
)
from weebot.application.ports.skill_index_port import RemoteSkill

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)


async def main(limit: int | None = None, dry_run: bool = False) -> None:
    adapter = AwesomeAgentSkillsAdapter()
    target_base = Path.home() / ".weebot" / "skills"

    print("Fetching awesome-agent-skills index...")
    skills = await adapter.fetch_index()
    print(f"  Parsed {len(skills)} skills from README\n")

    if limit:
        skills = skills[:limit]
        print(f"  (limited to first {limit})\n")

    succeeded: list[str] = []
    failed: list[tuple[str, str]] = []  # (name, reason)
    skipped: list[str] = []

    for i, skill in enumerate(skills, 1):
        target_dir = target_base / skill.name
        skill_md = target_dir / "SKILL.md"

        prefix = f"[{i}/{len(skills)}]"

        if dry_run:
            print(f"  {prefix} {skill.author}/{skill.name} — {skill.description[:60]}")
            continue

        # Check if already exists and was recently downloaded (skip re-download)
        if skill_md.exists():
            skipped.append(skill.name)
            print(f"  {prefix} {skill.name} — already exists, skipping")
            continue

        print(f"  {prefix} Downloading {skill.author}/{skill.name}...", end=" ", flush=True)
        ok = await adapter.download(skill, str(target_dir))

        if ok:
            succeeded.append(skill.name)
            print("OK")
        else:
            failed.append((skill.name, f"{skill.author}/{skill.name}"))
            print("FAILED")

    await adapter.close()

    if dry_run:
        print(f"\nDry run complete. {len(skills)} skills would be downloaded.")
        return

    # Summary
    print("\n" + "=" * 60)
    print(f"Download Summary")
    print(f"=" * 60)
    print(f"  Succeeded: {len(succeeded)}")
    print(f"  Skipped:   {len(skipped)} (already installed)")
    print(f"  Failed:    {len(failed)}")

    if failed:
        print(f"\n  Failed skills ({len(failed)}):")
        for name, owner_name in failed:
            print(f"    - {owner_name}")

    if succeeded:
        print(f"\n  Rebuilding BM25 index...")
        try:
            from weebot.application.skills.skill_registry import SkillRegistry
            from weebot.application.services.bm25_skill_retriever import BM25SkillRetriever

            registry = SkillRegistry()
            registry.load_all()
            retriever = BM25SkillRetriever(registry)
            n = len(registry.list_skills())
            has_bm25 = getattr(retriever, '_bm25', None) is not None
            engine = "BM25" if has_bm25 else "word-overlap"
            print(f"  {engine} index rebuilt ({n} skills)")
        except Exception as exc:
            print(f"  Index rebuild skipped: {exc}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download awesome-agent-skills")
    parser.add_argument("--limit", type=int, default=None, help="Max skills to download")
    parser.add_argument("--dry-run", action="store_true", help="List skills without downloading")
    args = parser.parse_args()
    asyncio.run(main(limit=args.limit, dry_run=args.dry_run))
