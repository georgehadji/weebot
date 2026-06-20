"""Tests for HARDEN mode security features.

Verifies all 5 hardening measures:
1. Privacy Audit Middleware
2. Rate Limiter Bounds
3. YAML Security Limits
4. Circuit Breaker Jitter
5. DB Pool Monitoring
"""
import asyncio
import pytest
from datetime import datetime


class TestPrivacyAuditMiddleware:
    """Test privacy audit middleware protections."""
    
    def test_blocks_collaborative_query_below_min_user_count(self):
        """Privacy: Blocks queries with insufficient user count."""
        from weebot.templates.privacy_audit import PrivacyAuditMiddleware
        
        audit = PrivacyAuditMiddleware(min_user_count=3)
        
        # Should block with proposed_user_count < min_user_count
        result = audit.allow_collaborative_query(
            template_name="test_template",
            user_id="user123",
            proposed_user_count=2,  # Below minimum
        )
        
        assert result is False
        
        # Check violation was logged
        report = audit.get_report()
        assert report.violations == 1
        assert report.blocked_operations == 1
    
    def test_allows_collaborative_query_with_sufficient_count(self):
        """Privacy: Allows queries meeting minimum user count."""
        from weebot.templates.privacy_audit import PrivacyAuditMiddleware
        
        audit = PrivacyAuditMiddleware(min_user_count=3)
        
        result = audit.allow_collaborative_query(
            template_name="test_template",
            user_id="user123",
            proposed_user_count=5,  # Above minimum
        )
        
        assert result is True
        
        report = audit.get_report()
        assert report.violations == 0
    
    def test_compliance_score_calculation(self):
        """Privacy: Compliance score reflects violation ratio."""
        from weebot.templates.privacy_audit import PrivacyAuditMiddleware
        
        audit = PrivacyAuditMiddleware(min_user_count=3)
        
        # 3 allowed, 1 blocked
        audit.allow_collaborative_query("t1", "u1", proposed_user_count=5)
        audit.allow_collaborative_query("t2", "u2", proposed_user_count=5)
        audit.allow_collaborative_query("t3", "u3", proposed_user_count=5)
        audit.allow_collaborative_query("t4", "u4", proposed_user_count=1)  # Blocked
        
        report = audit.get_report()
        assert report.compliance_score == 0.75  # 3/4


class TestRateLimiterBounds:
    """Test rate limiter memory bounds."""
    
    def test_enforces_max_buckets_limit(self):
        """RateLimiter: Enforces maximum bucket count."""
        from weebot.templates.production import RateLimiter, RateLimitConfig
        
        limiter = RateLimiter(
            backend="memory",
            config=RateLimitConfig(burst_size=10)
        )
        
        # Override max buckets for testing
        limiter.MAX_BUCKETS = 100
        
        # Create buckets up to limit
        for i in range(150):
            limiter.is_allowed(f"user_{i}", "test_resource")
        
        # Should have evicted some buckets
        metrics = limiter.get_metrics()
        assert metrics["active_buckets"] <= 100
        assert metrics["eviction_count"] > 0
    
    def test_metrics_tracking(self):
        """RateLimiter: Tracks utilization metrics."""
        from weebot.templates.production import RateLimiter

        limiter = RateLimiter(backend="memory")
        
        # Make some requests
        for i in range(10):
            limiter.is_allowed(f"user_{i}")
        
        metrics = limiter.get_metrics()
        assert metrics["total_requests"] == 10
        assert metrics["active_buckets"] == 10
        assert metrics["backend"] == "memory"


class TestYamlSecurityLimits:
    """Test YAML parsing security limits."""
    
    def test_rejects_excessive_nesting(self):
        """YAML: Rejects deeply nested structures."""
        from weebot.templates.parser import TemplateParser, TemplateSecurityError
        
        parser = TemplateParser()
        
        # Create deeply nested YAML (11 levels, max is 10)
        nested = "a: 1"
        for _ in range(11):
            nested = f"key:\n  {nested.replace(chr(10), chr(10) + '  ')}"
        
        with pytest.raises(TemplateSecurityError, match="nesting"):
            parser.parse(nested)
    
    def test_rejects_oversized_document(self):
        """YAML: Rejects documents exceeding size limit."""
        from weebot.templates.parser import TemplateParser, TemplateSecurityError
        
        parser = TemplateParser()
        
        # Create oversized document
        huge_content = "x: " + "A" * (parser.MAX_TEMPLATE_SIZE + 100)
        
        with pytest.raises(TemplateSecurityError, match="size"):
            parser.parse(huge_content)
    
    def test_rejects_too_many_parameters(self):
        """YAML: Rejects templates with excessive parameters."""
        from weebot.templates.parser import TemplateParser, TemplateSecurityError
        
        parser = TemplateParser()
        
        # Create template with 60 parameters (max is 50)
        params = "\n".join([f"  param_{i}:\n    type: string" for i in range(60)])
        yaml_content = f"""
name: test
description: Test template
parameters:
{params}
workflow:
  step1:
    type: agent_task
"""
        
        with pytest.raises(TemplateSecurityError, match="parameters"):
            parser.parse(yaml_content)
    
    def test_accepts_valid_template(self):
        """YAML: Accepts valid templates within limits."""
        from weebot.templates.parser import TemplateParser
        
        parser = TemplateParser()
        
        valid_yaml = """
name: test_template
version: "1.0.0"
description: A test template
parameters:
  topic:
    type: string
    description: Topic to research
    required: true
workflow:
  research:
    type: agent_task
    prompt: "Research {{topic}}"
output:
  result: "{{research.output}}"
"""
        
        template = parser.parse(valid_yaml)
        assert template.name == "test_template"
        assert "topic" in template.parameters


class TestCircuitBreakerJitter:
    """Test circuit breaker jitter features."""
    
    def test_jittered_cooldown_variation(self):
        """CircuitBreaker: Cooldown has jitter variation."""
        from weebot.core.circuit_breaker import CircuitBreaker
        
        breaker = CircuitBreaker(
            cooldown_seconds=60.0,
            jitter_percent=0.2,
        )
        
        # Get multiple jittered cooldowns
        cooldowns = [breaker._get_jittered_cooldown() for _ in range(100)]
        
        # All should be within 20% of base
        base = 60.0
        jitter = base * 0.2
        
        for cd in cooldowns:
            assert base - jitter <= cd <= base + jitter
        
        # Should have variation (not all identical)
        unique_cooldowns = len(set(round(c, 2) for c in cooldowns))
        assert unique_cooldowns > 1  # Some variation exists
    
    @pytest.mark.xfail(reason="Metrics tracking not yet implemented")
    def test_metrics_tracking(self):
        """CircuitBreaker: Tracks recovery metrics."""
        from weebot.core.circuit_breaker import CircuitBreaker
        
        breaker = CircuitBreaker(
            failure_threshold=1,
            cooldown_seconds=0.1,  # Fast for testing
            success_threshold=1,
        )
        
        # Trigger failure and recovery
        asyncio.run(breaker.record_failure("test_entity"))
        
        # Wait for cooldown
        import time
        time.sleep(0.15)
        
        # Probe should be allowed
        result = asyncio.run(breaker.evaluate("test_entity"))
        assert result.state.value == "half_open"
        
        # Record success to close
        asyncio.run(breaker.record_success("test_entity"))
        
        metrics = breaker.get_metrics()
        assert metrics["recovery_attempts"] >= 1
        assert metrics["state_changes"] >= 2  # OPEN -> HALF_OPEN -> CLOSED


class TestDbPoolMonitor:
    """Test database pool monitoring."""
    
    @pytest.mark.xfail(reason="Connection metrics not yet implemented")
    def test_tracks_connection_metrics(self):
        """PoolMonitor: Tracks connection acquisition."""
        from weebot.templates.db_monitor import ConnectionPoolMonitor
        
        monitor = ConnectionPoolMonitor(pool_size=10)
        
        # Simulate connection usage
        async def use_connection():
            async with monitor.track_connection() as conn_id:
                # Simulate query
                monitor.record_query_start(conn_id, "q1")
                await asyncio.sleep(0.01)
                monitor.record_query_end(conn_id, "q1", success=True)
        
        asyncio.run(use_connection())
        
        metrics = monitor.get_metrics()
        assert metrics["total_acquisitions"] == 1
        assert metrics["active_connections"] == 0  # Released
        assert metrics["active_queries"] == 0
    
    def test_saturation_alert_threshold(self):
        """PoolMonitor: Alerts on high saturation."""
        from weebot.templates.db_monitor import ConnectionPoolMonitor
        
        monitor = ConnectionPoolMonitor(
            pool_size=10,
            max_overflow=0,  # Total capacity = 10
            saturation_threshold=0.8,
        )
        
        # Record high saturation (9/10 = 90%)
        monitor.record_pool_snapshot(checked_out=9, available=1, waiting=2)
        
        metrics = monitor.get_metrics()
        assert metrics["saturation_alerts"] == 1
    
    @pytest.mark.xfail(reason="Recommendations generation not yet implemented")
    def test_recommendations_generation(self):
        """PoolMonitor: Generates actionable recommendations."""
        from weebot.templates.db_monitor import ConnectionPoolMonitor
        
        monitor = ConnectionPoolMonitor(pool_size=10)
        
        # Simulate high load
        for _ in range(100):
            monitor.record_pool_snapshot(checked_out=9, available=1)
        
        recommendations = monitor.get_recommendations()
        
        # Should suggest pool size increase
        assert any("saturation" in r.lower() for r in recommendations)


class TestHardenModeIntegration:
    """Integration tests for all hardening measures."""
    
    def test_all_harden_modules_importable(self):
        """All HARDEN modules can be imported."""
        from weebot.templates.privacy_audit import PrivacyAuditMiddleware
        from weebot.templates.production import RateLimiter
        from weebot.templates.parser import TemplateParser, SecureYamlLoader
        from weebot.core.circuit_breaker import CircuitBreaker
        from weebot.templates.db_monitor import ConnectionPoolMonitor
        
        # Verify key classes exist
        assert PrivacyAuditMiddleware is not None
        assert RateLimiter is not None
        assert TemplateParser is not None
        assert SecureYamlLoader is not None
        assert CircuitBreaker is not None
        assert ConnectionPoolMonitor is not None
