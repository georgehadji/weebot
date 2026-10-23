"""SkillCurator.detect_overlaps finds overlapping skills.

It iterated the return value of `registry.load_all()`, which is None, and read
`skill.body`, which Skill does not have (the field is `content`), so it always
returned [] and never suggested a merge.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from weebot.application.services.skill_curator import SkillCurator
from weebot.application.skills.skill_registry import SkillRegistry


async def test_two_near_identical_skills_are_reported(tmp_path):
    text = "scrape product prices from shopping websites into a spreadsheet"
    for name in ("price-scraper", "price-scraper-two"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {text}\n---\n\n{text}\n", encoding="utf-8"
        )
    curator = SkillCurator(registry=SkillRegistry(search_paths=[tmp_path]), llm=MagicMock())
    overlaps = await curator.detect_overlaps()
    assert {o["skill_a"] for o in overlaps} | {o["skill_b"] for o in overlaps} == {
        "price-scraper", "price-scraper-two",
    }
