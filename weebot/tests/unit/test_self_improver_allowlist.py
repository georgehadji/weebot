"""Tests for SelfImprover tier-2 allowlist and feature flag gating.

Tests Enhancement 7: metacognitive self-improvement access control.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from weebot.application.services.self_improver import (
    _get_effective_allowlist,
    _ALLOWED_TARGET_DIRS,
    _META_ALLOWED_TARGET_DIRS,
    SelfImprover,
)


class TestEffectiveAllowlist:
    """Tests for _get_effective_allowlist()."""

    @pytest.fixture(autouse=True)
    def _reset_feature_flags(self) -> None:
        """Ensure feature flags are reloaded in default state after each test."""
        yield
        import importlib
        from weebot.config import feature_flags
        importlib.reload(feature_flags)

    def test_default_does_not_include_meta(self) -> None:
        """Without feature flag, allowlist should NOT include meta-tier."""
        allowlist = _get_effective_allowlist()
        for meta_dir in _META_ALLOWED_TARGET_DIRS:
            assert meta_dir not in allowlist

    def test_default_includes_all_tier1(self) -> None:
        """Default allowlist should include all tier-1 directories."""
        allowlist = _get_effective_allowlist()
        for tier1_dir in _ALLOWED_TARGET_DIRS:
            assert tier1_dir in allowlist

    def test_with_feature_flag_includes_meta(self) -> None:
        """With env var set, allowlist should include meta-tier."""
        import importlib
        from weebot.config import feature_flags

        old = os.environ.get("WEEBOT_METACOGNITIVE_IMPROVEMENT")
        os.environ["WEEBOT_METACOGNITIVE_IMPROVEMENT"] = "1"
        try:
            importlib.reload(feature_flags)
            allowlist = _get_effective_allowlist()
            for meta_dir in _META_ALLOWED_TARGET_DIRS:
                assert meta_dir in allowlist
        finally:
            if old is not None:
                os.environ["WEEBOT_METACOGNITIVE_IMPROVEMENT"] = old
            else:
                del os.environ["WEEBOT_METACOGNITIVE_IMPROVEMENT"]
            importlib.reload(feature_flags)


class TestIsAllowedTarget:
    """Tests for _is_allowed_target with effective allowlist."""

    def test_allows_skill_files(self) -> None:
        assert SelfImprover._is_allowed_target("weebot/skills/builtin/my_skill.md")

    def test_allows_contract_files(self) -> None:
        assert SelfImprover._is_allowed_target("weebot/config/contracts/bash.yaml")

    def test_allows_prompt_variant_files(self) -> None:
        assert SelfImprover._is_allowed_target(
            "weebot/config/prompts/variants/abc123.txt"
        )

    def test_rejects_outside_allowlist(self) -> None:
        assert not SelfImprover._is_allowed_target("weebot/core/bash_guard.py")

    def test_rejects_wrong_extension(self) -> None:
        assert not SelfImprover._is_allowed_target("weebot/skills/builtin/skill.py")

    def test_allows_meta_when_feature_flag_on(self) -> None:
        """With feature flag, meta-tier files should be allowed."""
        import importlib
        from weebot.config import feature_flags

        old = os.environ.get("WEEBOT_METACOGNITIVE_IMPROVEMENT")
        os.environ["WEEBOT_METACOGNITIVE_IMPROVEMENT"] = "1"
        try:
            importlib.reload(feature_flags)
            assert SelfImprover._is_allowed_target(
                "weebot/application/services/self_improver.py"
            )
        finally:
            if old is not None:
                os.environ["WEEBOT_METACOGNITIVE_IMPROVEMENT"] = old
            else:
                del os.environ["WEEBOT_METACOGNITIVE_IMPROVEMENT"]
            importlib.reload(feature_flags)
