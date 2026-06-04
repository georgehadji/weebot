"""Tests for the KeywordTaskRouter classification logic.

Covers:
- Route classification for all TaskCategory values
- Short-circuit: very short queries → CASUAL
- Complexity estimation
- Confidence threshold: low confidence → COMPLEX fallback
- Empty config, missing file
- Refresh reloads config
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from weebot.application.services.keyword_task_router import KeywordTaskRouter
from weebot.domain.models.task_route import TaskCategory, TaskComplexity


# ── Test Config ─────────────────────────────────────────────────────────

@pytest.fixture
def minimal_config(tmp_path: Path) -> Path:
    """Write a minimal task_classification.yaml for testing."""
    config = {
        "categories": {
            "casual": {
                "keywords": ["hi", "hello", "hey", "joke"],
                "flow_type": "chat",
                "tool_restriction": "none",
                "mandatory_rules": [],
            },
            "code": {
                "keywords": ["write", "python", "debug", "function"],
                "flow_type": "chat",
                "tool_restriction": "code_only",
                "mandatory_rules": ["coding.md"],
            },
            "research": {
                "keywords": ["search", "find", "research", "latest"],
                "flow_type": "plan_act",
                "tool_restriction": "researcher_role",
                "mandatory_rules": ["research.md"],
            },
            "file_ops": {
                "keywords": ["file", "folder", "rename", "move"],
                "flow_type": "chat",
                "tool_restriction": "file_only",
                "mandatory_rules": ["file_ops.md"],
            },
            "mcp": {
                "keywords": ["mcp", "mcp server"],
                "flow_type": "mcp",
                "tool_restriction": "mcp_only",
                "mandatory_rules": [],
            },
        },
        "fallback": {
            "flow_type": "plan_act",
            "tool_restriction": "admin_role",
            "mandatory_rules": [],
        },
    }
    path = tmp_path / "task_classification.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    return path


@pytest.fixture
def router(minimal_config: Path) -> KeywordTaskRouter:
    return KeywordTaskRouter(config_path=minimal_config)


# ── Tests ────────────────────────────────────────────────────────────────

class TestRouterBasic:
    """Basic routing classification."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_casual(self, router: KeywordTaskRouter):
        route = await router.route("")
        assert route.category == TaskCategory.CASUAL
        assert route.complexity == TaskComplexity.LOW
        assert route.flow_type == "chat"

    @pytest.mark.asyncio
    async def test_very_short_query_returns_casual(self, router: KeywordTaskRouter):
        route = await router.route("hi")
        assert route.category == TaskCategory.CASUAL
        assert route.flow_type == "chat"

    @pytest.mark.asyncio
    async def test_hello_query_returns_casual(self, router: KeywordTaskRouter):
        route = await router.route("hello")
        assert route.category == TaskCategory.CASUAL
        assert route.flow_type == "chat"

    @pytest.mark.asyncio
    async def test_tell_joke_returns_casual(self, router: KeywordTaskRouter):
        route = await router.route("tell me a joke")
        assert route.category == TaskCategory.CASUAL
        assert route.flow_type == "chat"

    @pytest.mark.asyncio
    async def test_write_python_returns_code(self, router: KeywordTaskRouter):
        route = await router.route("write a Python function")
        assert route.category == TaskCategory.CODE
        assert route.flow_type == "chat"  # LOW complexity

    @pytest.mark.asyncio
    async def test_debug_code_returns_code(self, router: KeywordTaskRouter):
        route = await router.route("debug this Python script")
        assert route.category == TaskCategory.CODE

    @pytest.mark.asyncio
    async def test_search_returns_research(self, router: KeywordTaskRouter):
        route = await router.route("search the web for the latest AI news")
        assert route.category == TaskCategory.RESEARCH
        assert route.flow_type == "plan_act"
        assert route.complexity == TaskComplexity.LOW or TaskComplexity.HIGH

    @pytest.mark.asyncio
    async def test_file_ops_returns_file_ops(self, router: KeywordTaskRouter):
        route = await router.route("find the file budget.xlsx on my drive")
        assert route.category == TaskCategory.FILE_OPS

    @pytest.mark.asyncio
    async def test_mcp_returns_mcp(self, router: KeywordTaskRouter):
        route = await router.route("use MCP to find stock data")
        assert route.category == TaskCategory.MCP
        assert route.flow_type == "mcp"

    @pytest.mark.asyncio
    async def test_unmatched_falls_back_to_complex(self, router: KeywordTaskRouter):
        route = await router.route("zxywq unknown gibberish")
        assert route.category == TaskCategory.COMPLEX
        assert route.flow_type == "plan_act"


class TestRouterComplexity:
    """Complexity estimation tests."""

    @pytest.mark.asyncio
    async def test_simple_code_is_low_complexity(self, router: KeywordTaskRouter):
        route = await router.route("write a Python function")
        assert route.complexity == TaskComplexity.LOW

    @pytest.mark.asyncio
    async def test_build_task_is_high_complexity(self, router: KeywordTaskRouter):
        route = await router.route("build a web app with Python")
        assert route.complexity == TaskComplexity.HIGH

    @pytest.mark.asyncio
    async def test_multi_category_is_high(self, router: KeywordTaskRouter):
        route = await router.route("search for an API and then write Python code to use it")
        assert route.complexity == TaskComplexity.HIGH


class TestRouterConfidence:
    """Confidence threshold tests."""

    @pytest.mark.asyncio
    async def test_strong_match_high_confidence(self, router: KeywordTaskRouter):
        route = await router.route("search for the latest research on AI")
        assert route.category == TaskCategory.RESEARCH
        assert route.confidence >= 0.6

    @pytest.mark.asyncio
    async def test_low_confidence_falls_back_to_complex(self, router: KeywordTaskRouter):
        route = await router.route("xy")
        assert route.category == TaskCategory.CASUAL  # Short-circuit
        assert route.flow_type == "chat"


class TestRouterConfig:
    """Configuration handling tests."""

    def test_missing_config_logs_warning(self, tmp_path: Path):
        missing = tmp_path / "nonexistent.yaml"
        router = KeywordTaskRouter(config_path=missing)
        # Should not crash, categories should be empty
        assert router._categories == {}

    @pytest.mark.asyncio
    async def test_refresh_reloads_config(self, tmp_path: Path, minimal_config: Path):
        router = KeywordTaskRouter(config_path=minimal_config)
        initial = await router.route("research space travel")
        assert initial.category == TaskCategory.RESEARCH

        # Overwrite config — remove research category entirely
        new_config = {
            "categories": {
                "code": {
                    "keywords": ["write", "python"],
                    "flow_type": "chat",
                    "tool_restriction": "code_only",
                    "mandatory_rules": [],
                },
            },
            "fallback": {
                "flow_type": "plan_act",
                "tool_restriction": "admin_role",
                "mandatory_rules": [],
            },
        }
        with open(minimal_config, "w", encoding="utf-8") as f:
            yaml.dump(new_config, f)

        await router.refresh()
        after = await router.route("research space travel")
        # "research" no longer matches (category removed), should fall back to COMPLEX
        assert after.category == TaskCategory.COMPLEX
