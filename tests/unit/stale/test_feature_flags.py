"""Tests for feature flags and metacognitive improvement gating."""
from __future__ import annotations

import os
import pytest


class TestFeatureFlags:
    """Tests for the feature flag system."""

    def test_import_does_not_crash(self) -> None:
        """Feature flags module should import without errors."""
        from weebot.config import feature_flags
        assert hasattr(feature_flags, "METACOGNITIVE_IMPROVEMENT_ENABLED")

    def test_metacognitive_improvement_defaults_off(self) -> None:
        """Without env var, metacognitive improvement should be OFF."""
        import importlib
        from weebot.config import feature_flags

        old = os.environ.pop("WEEBOT_METACOGNITIVE_IMPROVEMENT", None)
        try:
            importlib.reload(feature_flags)
            assert feature_flags.METACOGNITIVE_IMPROVEMENT_ENABLED is False
        finally:
            if old is not None:
                os.environ["WEEBOT_METACOGNITIVE_IMPROVEMENT"] = old
            importlib.reload(feature_flags)

    def test_is_enabled_for_known_flag(self) -> None:
        from weebot.config.feature_flags import is_enabled
        # METACOGNITIVE_IMPROVEMENT_ENABLED is always defined
        result = is_enabled("METACOGNITIVE_IMPROVEMENT_ENABLED")
        assert isinstance(result, bool)

    def test_is_enabled_for_nonexistent_flag(self) -> None:
        from weebot.config.feature_flags import is_enabled
        assert is_enabled("NONEXISTENT_FLAG") is False

    def test_require_raises_when_disabled(self) -> None:
        from weebot.config.feature_flags import require
        # METACOGNITIVE_IMPROVEMENT_ENABLED defaults to False
        with pytest.raises(RuntimeError, match="disabled"):
            require("METACOGNITIVE_IMPROVEMENT_ENABLED")

    def test_require_passes_when_enabled(self) -> None:
        """With the env var set, require() should not raise."""
        import importlib
        from weebot.config import feature_flags

        old_val = os.environ.get("WEEBOT_METACOGNITIVE_IMPROVEMENT")
        os.environ["WEEBOT_METACOGNITIVE_IMPROVEMENT"] = "1"
        try:
            importlib.reload(feature_flags)
            # Should not raise
            feature_flags.require("METACOGNITIVE_IMPROVEMENT_ENABLED")
        finally:
            if old_val is not None:
                os.environ["WEEBOT_METACOGNITIVE_IMPROVEMENT"] = old_val
            else:
                del os.environ["WEEBOT_METACOGNITIVE_IMPROVEMENT"]
            # Reload to restore default state
            importlib.reload(feature_flags)
