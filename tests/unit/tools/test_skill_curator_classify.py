"""Unit tests for SkillCurator._classify() mtime fallback (Fix 1).

Covers:
- Freshly installed skill with source_path → classified as 'active'
- Skill without source_path and no history → 'archive-candidate'
- Old file mtime → 'stale' or 'archive-candidate'
"""
import os
import time
import pytest
from datetime import datetime, timezone

from weebot.application.services.skill_curator import SkillCurator
from weebot.domain.models.skill import Skill


class TestSkillCuratorClassifyMtime:
    """Validates SkillCurator._classify() mtime fallback logic."""

    def test_no_history_with_source_path_recent_is_active(self, tmp_path):
        """A freshly created SKILL.md with no evolution_log or versions
        should be classified as 'active' via mtime fallback."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: new-skill\ndescription: x\n---\n")
        skill = Skill(name="new-skill", source_path=str(skill_md))
        now = datetime.now(timezone.utc)
        result = SkillCurator._classify(skill, now)
        assert result == "active"

    def test_no_history_no_source_path_is_archive_candidate(self):
        """A skill with no source_path and no history falls through
        to age_days 999 → 'archive-candidate'."""
        skill = Skill(name="orphan-skill")
        now = datetime.now(timezone.utc)
        result = SkillCurator._classify(skill, now)
        assert result == "archive-candidate"

    def test_no_history_with_old_file_is_stale(self, tmp_path):
        """A skill with a 60-day-old SKILL.md and no history gets
        classified as 'stale' via mtime (between ACTIVE_DAYS and STALE_DAYS)."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: old-skill\ndescription: x\n---\n")
        # Backdate mtime by 60 days
        old_mtime = time.time() - (60 * 86400)
        os.utime(skill_md, (old_mtime, old_mtime))
        skill = Skill(name="old-skill", source_path=str(skill_md))
        now = datetime.now(timezone.utc)
        result = SkillCurator._classify(skill, now)
        assert result == "stale"

    def test_no_history_with_very_old_file_is_archive_candidate(self, tmp_path):
        """A skill with a 100-day-old SKILL.md and no history gets
        classified as 'archive-candidate' via mtime (>= STALE_DAYS)."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: ancient-skill\ndescription: x\n---\n")
        old_mtime = time.time() - (100 * 86400)
        os.utime(skill_md, (old_mtime, old_mtime))
        skill = Skill(name="ancient-skill", source_path=str(skill_md))
        now = datetime.now(timezone.utc)
        result = SkillCurator._classify(skill, now)
        assert result == "archive-candidate"

    def test_evolution_log_still_takes_priority_over_mtime(self, tmp_path):
        """If a skill has an evolution_log entry, its timestamp is used
        instead of mtime — even if the file is new."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: logged-skill\ndescription: x\n---\n")
        from weebot.domain.models.skill import EvolutionEntry
        skill = Skill(
            name="logged-skill",
            source_path=str(skill_md),
            evolution_log=[
                EvolutionEntry(
                    epoch=0,
                    narrative="Used at some point",
                    timestamp=datetime(2023, 1, 1, tzinfo=timezone.utc),
                )
            ],
        )
        now = datetime.now(timezone.utc)
        result = SkillCurator._classify(skill, now)
        # Over 90 days since last evolution entry → archive-candidate
        assert result == "archive-candidate"
