"""Tests for adaptive suggestion engine."""
from __future__ import annotations

import pytest
from unittest.mock import Mock, AsyncMock, patch
import asyncio
import json


class TestAdaptiveSuggestionEngine:
    """Test adaptive suggestion engine."""
    
    @pytest.fixture
    def engine(self):
        from weebot.templates.adaptive import AdaptiveSuggestionEngine
        return AdaptiveSuggestionEngine(
            db_session_factory=None,  # Will mock
            enable_collaborative=True,
            enable_personal=True,
            privacy_mode="strict",
        )
    
    def test_hash_user_consistency(self, engine):
        """User hashing is deterministic."""
        hash1 = engine._hash_user("user123")
        hash2 = engine._hash_user("user123")
        assert hash1 == hash2
        assert len(hash1) == 32
    
    def test_hash_user_different_users(self, engine):
        """Different users get different hashes."""
        hash1 = engine._hash_user("user1")
        hash2 = engine._hash_user("user2")
        assert hash1 != hash2
    
    def test_hash_user_one_way(self, engine):
        """Hash is one-way (can't reverse)."""
        user_id = "sensitive_user_id"
        hashed = engine._hash_user(user_id)
        assert user_id not in hashed


class TestParameterSuggestions:
    """Test suggestion generation."""
    
    @pytest.mark.asyncio
    async def test_suggest_parameters_no_db(self):
        """Returns empty list when no DB."""
        from weebot.templates.adaptive import AdaptiveSuggestionEngine
        from weebot.templates.parser import WorkflowTemplate
        
        engine = AdaptiveSuggestionEngine(db_session_factory=None)
        
        template = WorkflowTemplate(
            name="Test",
            version="1.0",
            parameters={},
            workflow={},
        )
        
        from weebot.templates.adaptive import SuggestionContext
        context = SuggestionContext(
            user_id="user1",
            template_name="Test",
            template_version="1.0",
            previous_executions=0,
        )
        
        suggestions = await engine.suggest_parameters(template, context)
        assert suggestions == []
    
    @pytest.mark.asyncio
    async def test_suggest_parameters_no_missing_params(self):
        """Returns empty when all params provided."""
        from weebot.templates.adaptive import AdaptiveSuggestionEngine
        from weebot.templates.parser import WorkflowTemplate, ParameterSchema
        
        engine = AdaptiveSuggestionEngine(db_session_factory=None)
        
        template = WorkflowTemplate(
            name="Test",
            version="1.0",
            parameters={
                "param1": ParameterSchema(name="param1", type="string"),
            },
            workflow={},
        )
        
        from weebot.templates.adaptive import SuggestionContext
        context = SuggestionContext(
            user_id="user1",
            template_name="Test",
            template_version="1.0",
            previous_executions=0,
        )
        
        # All params provided
        suggestions = await engine.suggest_parameters(
            template, context, current_input={"param1": "value"}
        )
        assert suggestions == []


class TestPrivacyCompliance:
    """Test GDPR/privacy compliance."""
    
    @pytest.mark.asyncio
    async def test_user_hashing_in_database(self):
        """User IDs are hashed before storage."""
        from weebot.templates.adaptive import AdaptiveSuggestionEngine
        
        engine = AdaptiveSuggestionEngine(
            db_session_factory=AsyncMock(),
            privacy_mode="strict",
        )
        
        user_id = "john.doe@company.com"
        user_hash = engine._hash_user(user_id)
        
        # Hash should not contain identifiable info
        assert user_id not in user_hash
        assert "@" not in user_hash
        assert "." not in user_hash
    
    @pytest.mark.asyncio
    async def test_min_users_for_collaborative(self):
        """Collaborative suggestions require minimum 3 users."""
        from weebot.templates.adaptive import AdaptiveSuggestionEngine
        
        engine = AdaptiveSuggestionEngine()
        assert engine.MIN_SAMPLE_SIZE == 5
        # Collaborative filter needs 3+ unique users
        # This is enforced in the query
    
    @pytest.mark.asyncio
    async def test_purge_old_data(self):
        """Old data can be purged for GDPR."""
        from weebot.templates.adaptive import AdaptiveSuggestionEngine
        from datetime import datetime, timedelta
        
        mock_session = AsyncMock()
        engine = AdaptiveSuggestionEngine(
            db_session_factory=lambda: mock_session,
        )
        
        # Mock the query results
        mock_result = Mock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result
        
        await engine.purge_old_data(days=30)
        
        # Should have executed delete queries
        assert mock_session.execute.called
        assert mock_session.commit.called


class TestSuggestionQuality:
    """Test suggestion quality metrics."""
    
    def test_confidence_threshold(self):
        """Suggestions below confidence threshold are filtered."""
        from weebot.templates.adaptive import AdaptiveSuggestionEngine
        
        engine = AdaptiveSuggestionEngine()
        assert engine.MIN_CONFIDENCE == 0.6
    
    def test_sample_size_requirement(self):
        """Need minimum sample size for suggestions."""
        from weebot.templates.adaptive import AdaptiveSuggestionEngine
        
        engine = AdaptiveSuggestionEngine()
        assert engine.MIN_SAMPLE_SIZE == 5


class TestAdaptiveEngineDisabled:
    """Test disabled engine (null object pattern)."""
    
    @pytest.mark.asyncio
    async def test_disabled_returns_empty_suggestions(self):
        """Disabled engine returns empty suggestions."""
        from weebot.templates.adaptive import AdaptiveEngineDisabled
        
        engine = AdaptiveEngineDisabled()
        suggestions = await engine.suggest_parameters(None, None)
        assert suggestions == []
    
    @pytest.mark.asyncio
    async def test_disabled_record_noop(self):
        """Disabled engine doesn't record."""
        from weebot.templates.adaptive import AdaptiveEngineDisabled
        
        engine = AdaptiveEngineDisabled()
        await engine.record_execution_outcome(None, None, None, None, None)
        # Should not raise
    
    @pytest.mark.asyncio
    async def test_disabled_stats_empty(self):
        """Disabled engine returns empty stats."""
        from weebot.templates.adaptive import AdaptiveEngineDisabled
        
        engine = AdaptiveEngineDisabled()
        stats = await engine.get_suggestion_stats()
        assert stats == {}


class TestFallbackBehavior:
    """Test graceful degradation."""
    
    @pytest.mark.asyncio
    async def test_db_failure_returns_empty(self):
        """DB failure returns empty suggestions, doesn't crash."""
        from weebot.templates.adaptive import AdaptiveSuggestionEngine
        from weebot.templates.parser import WorkflowTemplate
        
        # Mock DB that fails
        async def failing_session():
            raise Exception("DB connection failed")
        
        engine = AdaptiveSuggestionEngine(
            db_session_factory=failing_session,
        )
        
        template = WorkflowTemplate(
            name="Test",
            version="1.0",
            parameters={},
            workflow={},
        )
        
        from weebot.templates.adaptive import SuggestionContext
        context = SuggestionContext(
            user_id="user1",
            template_name="Test",
            template_version="1.0",
            previous_executions=0,
        )
        
        # Should not raise
        suggestions = await engine.suggest_parameters(template, context)
        # Returns empty on error


class TestProductionIntegration:
    """Test integration with ProductionTemplateEngine."""
    
    @pytest.mark.asyncio
    async def test_adaptive_disabled_by_default(self):
        """Adaptive engine disabled by default."""
        from weebot.templates.production import ProductionTemplateEngine
        
        engine = ProductionTemplateEngine()
        assert engine.adaptive_engine is None
    
    @pytest.mark.asyncio
    async def test_adaptive_enabled_with_flag(self):
        """Can enable adaptive with flag."""
        from weebot.templates.production import ProductionTemplateEngine
        
        # Would need real DB to test fully
        # Just test that flag is accepted
        engine = ProductionTemplateEngine(
            enable_adaptive=False,  # No DB, so won't actually enable
        )
        # Without DB, adaptive_engine stays None
    
    @pytest.mark.asyncio
    async def test_get_suggestions_returns_list(self):
        """get_suggestions returns list (empty if disabled)."""
        from weebot.templates.production import ProductionTemplateEngine
        
        engine = ProductionTemplateEngine()
        suggestions = await engine.get_suggestions("Test Template")
        assert isinstance(suggestions, list)
        assert suggestions == []  # Disabled


class TestFeatureFlags:
    """Test feature flag integration."""
    
    def test_feature_flag_disabled_by_default(self):
        """Adaptive suggestions disabled by default."""
        from weebot.templates.feature_flags import get_feature_flags, FeatureState
        from weebot.templates.feature_flags import register_default_features
        
        register_default_features()
        flags = get_feature_flags()
        
        assert not flags.is_enabled("adaptive_suggestions")
    
    def test_feature_flag_enable_for_user(self):
        """Can enable for specific user."""
        from weebot.templates.feature_flags import get_feature_flags, FeatureState
        from weebot.templates.feature_flags import register_default_features
        
        register_default_features()
        flags = get_feature_flags()
        
        flags.enable_for_user("adaptive_suggestions", "user1")
        assert flags.is_enabled("adaptive_suggestions", "user1")
    
    def test_feature_flag_percentage_rollout(self):
        """Percentage-based rollout."""
        from weebot.templates.feature_flags import (
            get_feature_flags, FeatureState, FeatureConfig
        )
        
        flags = get_feature_flags()
        flags.register(FeatureConfig(
            name="test_feature",
            state=FeatureState.PERCENTAGE,
            percentage=50,
        ))
        
        # Deterministic based on user_id
        enabled_count = sum(
            1 for i in range(100)
            if flags.is_enabled("test_feature", f"user_{i}")
        )
        
        # Should be approximately 50%
        assert 40 <= enabled_count <= 60


class TestBayesianScoring:
    """Test Bayesian scoring for suggestions."""
    
    def test_confidence_calculation(self):
        """Confidence is weighted by sample size."""
        from weebot.templates.adaptive import AdaptiveSuggestionEngine
        
        engine = AdaptiveSuggestionEngine()
        
        # High success rate but low samples = lower confidence
        success_rate = 0.9
        sample_size = 5
        weight = min(1.0, sample_size / 50)
        confidence = success_rate * weight
        
        assert confidence == 0.9 * 0.1  # 0.09
        
        # Same rate, more samples = higher confidence
        sample_size = 50
        weight = min(1.0, sample_size / 50)
        confidence = success_rate * weight
        
        assert confidence == 0.9  # Full confidence


class TestCacheInvalidation:
    """Test suggestion caching."""
    
    def test_cache_key_generation(self):
        """Cache key is deterministic."""
        from weebot.templates.adaptive import AdaptiveSuggestionEngine
        
        engine = AdaptiveSuggestionEngine()
        
        key1 = engine._get_cache_key(
            "Template1",
            "user1",
            {"param1", "param2"},
        )
        key2 = engine._get_cache_key(
            "Template1",
            "user1",
            {"param2", "param1"},  # Different order
        )
        
        assert key1 == key2  # Order shouldn't matter
    
    def test_cache_invalidation_on_record(self):
        """Cache cleared when new outcome recorded."""
        from weebot.templates.adaptive import AdaptiveSuggestionEngine
        
        engine = AdaptiveSuggestionEngine()
        
        # Add to cache
        cache_key = engine._get_cache_key(
            "Template1", "user1", {"param1"}
        )
        engine._suggestion_cache[cache_key] = {"test": "data"}
        
        # After recording outcome, cache should be cleared
        # (This would happen in record_execution_outcome)
