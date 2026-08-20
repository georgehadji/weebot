"""Unit tests for ACR Phase P1 — domain models, constraint checker, utility scorer, router."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from weebot.domain.models.capability import CapabilityAxis, ModelQualityProfile, TaskRequirement


class TestCapabilityDomain:
    """Domain model immutability and defaults."""

    def test_capability_axis_values(self):
        assert CapabilityAxis.REASONING.value == "reasoning"
        assert CapabilityAxis.CODING.value == "coding"
        assert CapabilityAxis.WRITING.value == "writing"
        assert CapabilityAxis.LEGAL.value == "legal"
        assert CapabilityAxis.MATH.value == "math"
        assert CapabilityAxis.CITATION.value == "citation"
        assert CapabilityAxis.PLANNING.value == "planning"
        assert CapabilityAxis.TOOL_USE.value == "tool_use"
        assert CapabilityAxis.LONG_CONTEXT.value == "long_context"
        assert len(CapabilityAxis) == 9

    def test_model_quality_profile_immutable(self):
        p = ModelQualityProfile(
            model_id="test/model", axes={CapabilityAxis.CODING: 8.5, CapabilityAxis.REASONING: 7.0}
        )
        assert p.model_id == "test/model"
        assert p.axes[CapabilityAxis.CODING] == 8.5
        assert p.source == "seed"
        # Pydantic frozen raises on attribute mutation
        with pytest.raises(Exception):
            p.model_id = "other"

    def test_model_quality_profile_axes_only_capabilities(self):
        """No cost/latency/context axes should ever appear in quality profiles."""
        p = ModelQualityProfile(
            model_id="test/model",
            axes={
                CapabilityAxis.CODING: 9.0,
                CapabilityAxis.REASONING: 8.0,
                CapabilityAxis.TOOL_USE: 7.5,
            },
        )
        for axis in p.axes:
            assert axis in CapabilityAxis, f"{axis} is not a valid capability axis"

    def test_task_requirement_minimal_defaults(self):
        r = TaskRequirement()
        assert r.requires_vision is False
        assert r.requires_tools is True
        assert r.min_context == 0
        assert CapabilityAxis.REASONING in r.quality_weights
        assert len(r.quality_weights) == 3  # reasoning, coding, tool_use
        assert r.utility_coeff["alpha"] == 0.4
        assert r.utility_coeff["beta"] == 0.3
        assert r.utility_coeff["delta"] == 0.2
        assert r.utility_coeff["epsilon"] == 0.1

    def test_task_requirement_vision_flag(self):
        r = TaskRequirement(requires_vision=True)
        assert r.requires_vision is True


class TestConstraintChecker:
    """ConstraintChecker gates must filter correctly."""

    def test_capability_gate_excludes_non_tool_models(self):
        from weebot.application.services.routing.constraint_checker import ConstraintChecker
        from weebot.domain.models.capability import TaskRequirement

        cc = ConstraintChecker()
        # Most models support function calling; find one that doesn't

        req = TaskRequirement(requires_tools=True)
        eligible = cc.eligible(["deepseek/deepseek-v4-flash"], req)
        assert "deepseek/deepseek-v4-flash" in eligible

    def test_vision_gate_excludes_non_vision_models(self):
        from weebot.application.services.routing.constraint_checker import ConstraintChecker
        from weebot.domain.models.capability import TaskRequirement

        cc = ConstraintChecker()
        req = TaskRequirement(requires_vision=True)
        # deepseek-v4-flash doesn't support vision
        eligible = cc.eligible(["deepseek/deepseek-v4-flash"], req)
        assert eligible == []

    def test_context_gate_fail_closed(self):
        from weebot.application.services.routing.constraint_checker import ConstraintChecker
        from weebot.domain.models.capability import TaskRequirement

        cc = ConstraintChecker()
        req = TaskRequirement(min_context=0)  # no requirement
        eligible = cc.eligible(["deepseek/deepseek-v4-flash"], req, context_tokens=999_999)
        assert eligible == []  # exceeds max_input_tokens

    def test_context_gate_skip_when_unknown(self):
        from weebot.application.services.routing.constraint_checker import ConstraintChecker
        from weebot.domain.models.capability import TaskRequirement

        cc = ConstraintChecker()
        req = TaskRequirement()
        eligible = cc.eligible(["deepseek/deepseek-v4-flash"], req, context_tokens=0)
        assert "deepseek/deepseek-v4-flash" in eligible

    def test_availability_gate_fail_open(self):
        from weebot.application.services.routing.constraint_checker import ConstraintChecker
        from weebot.domain.models.capability import TaskRequirement

        def _explode(_model_id):
            raise RuntimeError("probe failure")

        cc = ConstraintChecker(is_tripped=_explode)
        req = TaskRequirement()
        eligible = cc.eligible(["deepseek/deepseek-v4-flash"], req)
        assert "deepseek/deepseek-v4-flash" in eligible  # fail-open

    def test_availability_gate_excludes_tripped(self):
        from weebot.application.services.routing.constraint_checker import ConstraintChecker
        from weebot.domain.models.capability import TaskRequirement

        cc = ConstraintChecker(is_tripped=lambda m: m == "tripped-model")
        req = TaskRequirement()
        eligible = cc.eligible(["tripped-model", "deepseek/deepseek-v4-flash"], req)
        assert "tripped-model" not in eligible
        assert "deepseek/deepseek-v4-flash" in eligible


class TestUtilityScorer:
    """Utility function correctness — quality axes only, no mixed-unit cosine."""

    def test_quality_axes_not_contaminated(self):
        """Cost and latency must NOT appear in cap_match."""
        from weebot.application.services.routing.utility_scorer import UtilityScorer
        from weebot.application.services.task_model_router import TaskCategory

        scorer = UtilityScorer()
        scores = scorer.score(
            ["deepseek/deepseek-v4-flash", "minimax/minimax-m3"], TaskCategory.CODING
        )
        # cap_match must be ≤ 1.0 (cosine similarity bound)
        for s in scores:
            assert (
                0.0 <= s.cap_match <= 1.0001
            ), f"cap_match={s.cap_match} for {s.model_id} — should be a cosine"
            assert 0.0 <= s.cost_norm <= 1.0
            assert 0.0 <= s.lat_norm <= 1.0

    def test_empty_candidates_returns_empty(self):
        from weebot.application.services.routing.utility_scorer import UtilityScorer
        from weebot.application.services.task_model_router import TaskCategory

        scorer = UtilityScorer()
        scores = scorer.score([], TaskCategory.CODING)
        assert scores == []

    def test_single_candidate_score(self):
        from weebot.application.services.routing.utility_scorer import UtilityScorer
        from weebot.application.services.task_model_router import TaskCategory

        scorer = UtilityScorer()
        scores = scorer.score(["deepseek/deepseek-v4-flash"], TaskCategory.CODING)
        assert len(scores) == 1
        s = scores[0]
        assert s.model_id == "deepseek/deepseek-v4-flash"
        assert s.score > 0

    def test_unknown_model_fallback(self):
        """Unknown models get a neutral score."""
        from weebot.application.services.routing.utility_scorer import UtilityScorer
        from weebot.application.services.task_model_router import TaskCategory

        scorer = UtilityScorer()
        scores = scorer.score(["unknown-model-42"], TaskCategory.GENERAL)
        assert len(scores) == 1
        s = scores[0]
        assert s.cap_match == 0.0  # no profile → 0 cap_match

    def test_scored_candidates_sorted_descending(self):
        from weebot.application.services.routing.utility_scorer import UtilityScorer
        from weebot.application.services.task_model_router import TaskCategory

        scorer = UtilityScorer()
        scores = scorer.score(
            ["minimax/minimax-m3", "deepseek/deepseek-v4-flash", "x-ai/grok-build-0.1"],
            TaskCategory.CODING,
        )
        for i in range(len(scores) - 1):
            assert scores[i].score >= scores[i + 1].score, (
                f"Not sorted: {scores[i].model_id}={scores[i].score} "
                f"> {scores[i+1].model_id}={scores[i+1].score}"
            )


class TestAdaptiveCapabilityRouter:
    """Router must compose classify→constrain→score correctly."""

    def test_acr_disabled_returns_static(self):
        from weebot.application.services.routing.adaptive_capability_router import (
            AdaptiveCapabilityRouter,
        )

        acr = AdaptiveCapabilityRouter(force_acr=False)
        result = acr.route("refactor the database module")
        assert len(result) == 1
        # For CODING, the static map returns x-ai/grok-build-0.1
        assert result[0] == "x-ai/grok-build-0.1"

    def test_acr_enabled_returns_ordered_list(self):
        from weebot.application.services.routing.adaptive_capability_router import (
            AdaptiveCapabilityRouter,
        )

        acr = AdaptiveCapabilityRouter(force_acr=True)
        result = acr.route("refactor the database module")
        assert len(result) >= 2  # at least 2 candidates
        assert result[0] != result[1]  # distinct models

    def test_acr_falls_back_on_empty_description(self):
        from weebot.application.services.routing.adaptive_capability_router import (
            AdaptiveCapabilityRouter,
        )

        acr = AdaptiveCapabilityRouter(force_acr=True)
        result = acr.route("")  # empty → GENERAL
        assert len(result) >= 1

    def test_acr_shadow_mode_logs_but_returns_static(self):
        from weebot.application.services.routing.adaptive_capability_router import (
            AdaptiveCapabilityRouter,
        )

        with patch(
            "weebot.application.services.routing.adaptive_capability_router.WEEBOT_ACR_SHADOW", True
        ):
            acr = AdaptiveCapabilityRouter(force_acr=True)
            result = acr.route("search for Clean Architecture patterns")
            assert len(result) == 1  # returns static in shadow mode


class TestQualityProfiles:
    """Seed profiles and requirements must be complete."""

    def test_all_routed_models_have_profiles(self):
        """Every model in CATEGORY_MODEL must have a quality profile."""
        from weebot.application.services.task_model_router import CATEGORY_MODEL
        from weebot.config.capability_profiles import get_profile

        for cat, model_id in CATEGORY_MODEL.items():
            profile = get_profile(model_id)
            assert profile is not None, f"No quality profile for {model_id} (used by {cat.value})"

    def test_all_categories_have_requirements(self):
        from weebot.application.services.task_model_router import TaskCategory
        from weebot.config.capability_profiles import get_all_requirements

        reqs = get_all_requirements()
        for cat in TaskCategory:
            assert cat in reqs, f"Missing requirement for TaskCategory.{cat.name}"

    def test_seed_profiles_have_no_cost_or_latency_axes(self):
        """Cost and latency must not appear in quality profile axes."""
        from weebot.config.capability_profiles import get_all_profiles

        penalty_names = {"cost", "latency", "context"}
        for model_id, profile in get_all_profiles().items():
            for axis in profile.axes:
                assert (
                    axis.value not in penalty_names
                ), f"Penalty axis '{axis.value}' found in quality profile for {model_id}"

    def test_seed_profiles_are_immutable(self):
        from weebot.config.capability_profiles import get_profile

        profile = get_profile("minimax/minimax-m3")
        assert profile is not None
        assert profile.model_id == "minimax/minimax-m3"

    def test_kwaipilot_kat_coder_profiles_and_catalog(self):
        """Verify KwaiPilot KAT-Coder model configurations are present and valid."""
        from weebot.config.capability_profiles import get_profile
        from weebot.application.services.model_registry._catalog import MODELS
        from weebot.application.services.model_registry._models import ModelTier
        from weebot.domain.models.task_type import TaskType

        # Check profiles
        pro_profile = get_profile("kwaipilot/kat-coder-pro-v2.5")
        air_profile = get_profile("kwaipilot/kat-coder-air-v2.5")
        assert pro_profile is not None
        assert air_profile is not None
        assert pro_profile.axes.get("coding") == 9.5
        assert air_profile.axes.get("coding") == 9.0

        # Check catalog
        assert "kwaipilot/kat-coder-pro-v2.5" in MODELS
        assert "kwaipilot/kat-coder-air-v2.5" in MODELS
        pro_cfg = MODELS["kwaipilot/kat-coder-pro-v2.5"]
        air_cfg = MODELS["kwaipilot/kat-coder-air-v2.5"]
        assert pro_cfg.tier == ModelTier.STANDARD
        assert air_cfg.tier == ModelTier.STANDARD
        assert TaskType.CODE_GENERATION in pro_cfg.strengths
        assert TaskType.CODE_GENERATION in air_cfg.strengths
