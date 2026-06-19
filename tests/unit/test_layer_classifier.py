"""Unit tests for LayerClassifier.

Covers:
- All 6 Clean Architecture layers + unknown
- Edge cases: empty path, backslashes, leading ./
- Classification of previously-unknown modules from the empirical run
- layer_counts aggregation
"""
from __future__ import annotations

import pytest

from weebot.core.layer_classifier import layer_for_module, layer_counts


class TestLayerForModule:
    """Tests for layer_for_module()."""

    def test_domain(self):
        assert layer_for_module("weebot/domain/models/plan.py") == "domain"
        assert layer_for_module("weebot/domain/models/event.py") == "domain"
        assert layer_for_module("weebot/domain/exceptions.py") == "domain"

    def test_application(self):
        assert layer_for_module("weebot/application/services/skill_curator.py") == "application"
        assert layer_for_module("weebot/application/agents/planner.py") == "application"
        assert layer_for_module("weebot/application/flows/plan_act_flow.py") == "application"
        assert layer_for_module("weebot/application/ports/llm_port.py") == "application"
        assert layer_for_module("weebot/application/di/__init__.py") == "application"
        assert layer_for_module("weebot/application/cqrs/mediator.py") == "application"
        assert layer_for_module("weebot/application/eval/judges.py") == "application"

    def test_infrastructure(self):
        assert layer_for_module("weebot/infrastructure/persistence/skill_store.py") == "infrastructure"
        assert layer_for_module("weebot/infrastructure/event_bus.py") == "infrastructure"
        assert layer_for_module("weebot/infrastructure/mcp/mcp_client_manager.py") == "infrastructure"

    def test_tools_classified_as_infrastructure(self):
        """weebot/tools/* previously classified as 'unknown' — now infrastructure."""
        assert layer_for_module("weebot/tools/base.py") == "infrastructure"
        assert layer_for_module("weebot/tools/file_editor.py") == "infrastructure"
        assert layer_for_module("weebot/tools/bash_security.py") == "infrastructure"
        assert layer_for_module("weebot/tools/browser_tool.py") == "infrastructure"

    def test_qmd_classified_as_infrastructure(self):
        """weebot/qmd_integration/* previously 'unknown' — now infrastructure."""
        assert layer_for_module("weebot/qmd_integration/embeddings.py") == "infrastructure"
        assert layer_for_module("weebot/qmd_integration/query_expander.py") == "infrastructure"

    def test_interfaces(self):
        assert layer_for_module("weebot/interfaces/cli/agent_runner.py") == "interfaces"
        assert layer_for_module("weebot/interfaces/web/main.py") == "interfaces"
        assert layer_for_module("weebot/mcp/server.py") == "interfaces"

    def test_core(self):
        assert layer_for_module("weebot/core/agent.py") == "core"
        assert layer_for_module("weebot/core/bash_guard.py") == "core"
        assert layer_for_module("weebot/core/layer_classifier.py") == "core"
        assert layer_for_module("weebot/config/settings.py") == "core"
        assert layer_for_module("weebot/config/constants.py") == "core"

    def test_agents_classified_as_application(self):
        """weebot/agents/* previously 'unknown' — now application."""
        assert layer_for_module("weebot/agents/parser.py") == "application"
        assert layer_for_module("weebot/agent_core_v2.py") == "application"

    def test_tests(self):
        assert layer_for_module("tests/unit/test_layer_classifier.py") == "tests"
        assert layer_for_module("tests/integration/test_flow.py") == "tests"

    def test_unknown(self):
        """Paths without matching prefixes return 'unknown'."""
        assert layer_for_module("weebot/Output/project-manifest.md") == "unknown"
        assert layer_for_module("setup.py") == "unknown"
        assert layer_for_module("") == "unknown"

    def test_normalization_backslashes(self):
        """Backslashes are normalized to forward slashes."""
        assert layer_for_module("weebot\\domain\\models\\plan.py") == "domain"

    def test_normalization_leading_dot_slash(self):
        """Leading ./ is stripped."""
        assert layer_for_module("./weebot/domain/models/plan.py") == "domain"

    def test_prefix_takes_longer_match(self):
        """Longer prefix wins over shorter prefix.
        weebot/application/ports/ is application, not 'weebot/application' catch-all.
        """
        assert layer_for_module("weebot/application/ports/llm_port.py") == "application"
        # But weebot/application/ something without sub-prefix still matches
        assert layer_for_module("weebot/application/eval/judges.py") == "application"

    def test_gitnexus_is_unknown(self):
        """GitNexus vendor dir doesn't match any layer prefix."""
        assert layer_for_module("weebot/GitNexus-main/eval/bridge.py") == "unknown"


class TestLayerCounts:
    """Tests for layer_counts()."""

    def test_counts_all_layers(self):
        paths = [
            "weebot/domain/models/plan.py",
            "weebot/domain/models/event.py",
            "weebot/application/services/foo.py",
            "weebot/infrastructure/event_bus.py",
            "weebot/tools/base.py",  # now infrastructure
            "unknown/file.py",
        ]
        counts = layer_counts(paths)
        assert counts.get("domain") == 2
        assert counts.get("application") == 1
        assert counts.get("infrastructure") == 2
        assert counts.get("unknown") == 1

    def test_empty_input(self):
        assert layer_counts([]) == {}

    def test_all_classified(self):
        """Verify that previously-unknown modules from the empirical run are now classified."""
        previously_unknown = [
            "weebot/tools/base.py",           # → infrastructure
            "weebot/tools/file_editor.py",     # → infrastructure
            "weebot/agents/parser.py",         # → application
            "weebot/agents/models.py",         # → application
            "weebot/qmd_integration/embeddings.py",  # → infrastructure
            "weebot/skills/builtin/reasoner/prompt.md",  # → application
        ]
        for path in previously_unknown:
            assert layer_for_module(path) != "unknown", (
                f"Module {path} should not be 'unknown' after layer fixes"
            )
