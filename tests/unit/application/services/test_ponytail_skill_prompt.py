"""Unit tests for ponytail_skill_prompt."""

from __future__ import annotations

from weebot.application.services.ponytail_skill_prompt import (
    filter_skill_body_for_mode,
)


def test_filter_skill_body_for_mode():
    sample_body = (
        "---\n"
        "name: ponytail\n"
        "---\n"
        "# Ponytail\n\n"
        "## Intensity\n"
        "| Level | What change |\n"
        "|-------|------------|\n"
        "| **lite** | Build what's asked, but name the lazier alternative |\n"
        "| **full** | The ladder enforced. Stdlib and native first. |\n"
        "| **ultra** | YAGNI extremist. Deletion before addition. |\n\n"
        "Worked example:\n"
        "- lite: \"Done, cache added. FYI: lru_cache\"\n"
        "- full: \"@lru_cache on the fetch function.\"\n"
        "- ultra: \"No cache until a profiler says so.\"\n"
    )

    # Test full mode
    filtered_full = filter_skill_body_for_mode(sample_body, "full")
    assert "The ladder enforced. Stdlib and native first." in filtered_full
    assert "@lru_cache" in filtered_full
    assert "Done, cache added" not in filtered_full
    assert "No cache until" not in filtered_full

    # Test lite mode
    filtered_lite = filter_skill_body_for_mode(sample_body, "lite")
    assert "Build what's asked" in filtered_lite
    assert "Done, cache added" in filtered_lite
    assert "@lru_cache" not in filtered_lite
    assert "No cache until" not in filtered_lite

    # Test ultra mode
    filtered_ultra = filter_skill_body_for_mode(sample_body, "ultra")
    assert "YAGNI extremist" in filtered_ultra
    assert "No cache until" in filtered_ultra
    assert "Done, cache added" not in filtered_ultra
    assert "@lru_cache" not in filtered_ultra
