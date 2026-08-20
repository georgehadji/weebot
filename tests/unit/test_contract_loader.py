"""Unit tests for ContractLoader (Tier 3.2 — Environment Contract Layer)."""

from __future__ import annotations

from pathlib import Path

import pytest

from weebot.infrastructure.adapters.contract_loader import ContractLoader


@pytest.fixture
def contracts_dir(tmp_path: Path) -> Path:
    (tmp_path / "search.yaml").write_text(
        """
tool: search
description: Search the web.
pitfalls:
  - "Results may be stale — verify time-sensitive facts"
  - "Rate-limited to 10 requests/minute"
""",
        encoding="utf-8",
    )
    (tmp_path / "noop.yaml").write_text(
        """
tool: noop
description: Does nothing.
""",
        encoding="utf-8",
    )
    (tmp_path / "broken.yaml").write_text("tool: [unclosed", encoding="utf-8")
    return tmp_path


def test_loads_all_valid_contracts(contracts_dir: Path):
    loader = ContractLoader(contracts_dir=contracts_dir)
    assert len(loader) == 2
    assert loader.get("search") is not None
    assert loader.get("noop") is not None


def test_broken_yaml_is_skipped_not_fatal(contracts_dir: Path):
    loader = ContractLoader(contracts_dir=contracts_dir)
    assert loader.get("broken") is None


def test_enhance_description_appends_pitfalls(contracts_dir: Path):
    loader = ContractLoader(contracts_dir=contracts_dir)
    enhanced = loader.enhance_description("search", "Search the web.")
    assert "Search the web." in enhanced
    assert "Known pitfalls:" in enhanced
    assert "Rate-limited to 10 requests/minute" in enhanced


def test_enhance_description_unchanged_when_no_pitfalls(contracts_dir: Path):
    loader = ContractLoader(contracts_dir=contracts_dir)
    original = "Does nothing."
    assert loader.enhance_description("noop", original) == original


def test_enhance_description_unchanged_for_unknown_tool(contracts_dir: Path):
    loader = ContractLoader(contracts_dir=contracts_dir)
    original = "Some tool with no contract."
    assert loader.enhance_description("unknown_tool", original) == original


def test_missing_contracts_dir_is_not_fatal(tmp_path: Path):
    loader = ContractLoader(contracts_dir=tmp_path / "does_not_exist")
    assert len(loader) == 0
    assert loader.enhance_description("anything", "desc") == "desc"


def test_real_contracts_dir_loads_shipped_examples():
    loader = ContractLoader(contracts_dir="config/contracts/")
    assert loader.get("bash") is not None
    assert loader.get("python_execute") is not None
    assert loader.get("advanced_browser") is not None
    assert len(loader.get("bash").pitfalls) > 0
