"""Unit tests for cli_support utilities."""
from pathlib import Path

from weebot.cli_support import (
    detect_platform,
    build_plan_from_spec,
    compare_versions,
    init_project,
)


def test_detect_platform_codex(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("test", encoding="utf-8")
    platform, tier, signals = detect_platform(tmp_path)
    assert platform == "codex"
    assert "AGENTS.md" in signals[0]


def test_build_plan_from_spec_bullets():
    plan = build_plan_from_spec("- step one\n- step two\n")
    assert len(plan) == 2
    assert plan[0]["prompt"] == "step one"
    assert plan[1]["prompt"] == "step two"


def test_compare_versions():
    assert compare_versions("1.2.0", "1.10.0") == -1
    assert compare_versions("2.0.0", "1.9.9") == 1
    assert compare_versions("1.0", "1.0.0") == 0


def test_init_project_creates_config(tmp_path: Path):
    config_path = init_project(tmp_path, platform="generic", force=True, create_env=False)
    assert config_path.exists()
