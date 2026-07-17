"""Tests for CatalogValidator — cascade/catalog cross-validation.

The headline test is ``test_default_catalog_is_clean``: it asserts the real
shipped catalog and the real role cascades agree. Without it, drift between
``_ROLE_MODEL_CASCADE`` and the model catalog only ever surfaced as a startup
log line that nothing failed on.
"""
from __future__ import annotations

import pytest

from weebot.application.services.model_registry._models import ModelConfig, ModelTier
from weebot.config._catalog_validator import CatalogValidator
from weebot.domain.models.task_type import TaskType


def _cfg(provider: str) -> ModelConfig:
    """Minimal catalog entry with the given provider."""
    return ModelConfig(
        name="Test Model",
        provider=provider,
        cost_per_1k_tokens=0.001,
        context_window=128000,
        strengths=[TaskType.CHAT],
        tier=ModelTier.STANDARD,
        api_key_env="OPENROUTER_API_KEY",
    )


# ── the real catalog ──────────────────────────────────────────────────

class TestDefaultCatalog:
    def test_default_catalog_is_clean(self):
        """Every model in every role cascade resolves with a matching provider.

        Regression: ``openai/gpt-4o`` in the ``vision`` cascade was tagged
        provider="openai" while every sibling routed through OpenRouter
        carried provider="openrouter" — contradicting its own
        api_key_env="OPENROUTER_API_KEY".
        """
        report = CatalogValidator.run_default_validation()
        assert report.warning_count == 0, (
            "Catalog/cascade drift:\n  "
            + "\n  ".join(str(w) for w in report.warnings)
        )

    def test_default_validation_actually_checks_models(self):
        """Guard against the clean result being vacuous."""
        report = CatalogValidator.run_default_validation()
        assert report.total_models_checked > 0


# ── provider mismatch ─────────────────────────────────────────────────

class TestProviderMismatch:
    def test_mismatched_provider_is_flagged(self):
        report = CatalogValidator().validate(
            role_cascades={"vision": ["openai/gpt-4o"]},
            catalog={"openai/gpt-4o": _cfg("openai")},
        )
        assert report.warning_count == 1
        assert report.warnings[0].field == "provider_mismatch"
        assert report.warnings[0].expected == "openrouter"
        assert report.warnings[0].actual == "openai"

    def test_matching_provider_is_not_flagged(self):
        report = CatalogValidator().validate(
            role_cascades={"vision": ["openai/gpt-4o"]},
            catalog={"openai/gpt-4o": _cfg("openrouter")},
        )
        assert report.warning_count == 0

    def test_direct_provider_prefix_matches_itself(self):
        """deepseek/* is a direct provider, not routed via OpenRouter."""
        report = CatalogValidator().validate(
            role_cascades={"coder": ["deepseek/deepseek-v4-flash"]},
            catalog={"deepseek/deepseek-v4-flash": _cfg("deepseek")},
        )
        assert report.warning_count == 0


# ── missing models ────────────────────────────────────────────────────

class TestMissingModel:
    def test_model_absent_from_catalog_is_flagged(self):
        report = CatalogValidator().validate(
            role_cascades={"vision": ["openai/does-not-exist"]},
            catalog={},
        )
        assert report.warning_count == 1
        assert report.warnings[0].field == "missing"


# ── routing suffixes ──────────────────────────────────────────────────

class TestRoutingSuffixes:
    @pytest.mark.parametrize("suffix", [":thinking", ":free", ":nitro"])
    def test_routing_suffix_resolves_to_base_model(self, suffix):
        """`:thinking` etc. are runtime variants, not distinct catalog IDs."""
        report = CatalogValidator().validate(
            role_cascades={"planner": [f"z-ai/glm-5.2{suffix}"]},
            catalog={"z-ai/glm-5.2": _cfg("openrouter")},
        )
        assert report.warning_count == 0

    def test_suffixed_model_still_flags_provider_mismatch(self):
        """Suffix stripping must not mask a genuine mismatch."""
        report = CatalogValidator().validate(
            role_cascades={"planner": ["z-ai/glm-5.2:thinking"]},
            catalog={"z-ai/glm-5.2": _cfg("wrong-provider")},
        )
        assert report.warning_count == 1
        assert report.warnings[0].field == "provider_mismatch"


# ── malformed input ───────────────────────────────────────────────────

class TestMalformedCascade:
    def test_non_list_cascade_is_skipped_not_crashed(self):
        report = CatalogValidator().validate(
            role_cascades={"bogus": "not-a-list"},  # type: ignore[dict-item]
            catalog={},
        )
        assert report.total_models_checked == 0
        assert report.warning_count == 0
