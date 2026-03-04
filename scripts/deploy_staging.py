#!/usr/bin/env python3
"""Staging Deployment Script for HARDEN Mode.

This script:
1. Validates all HARDEN mode implementations
2. Runs regression tests on existing functionality
3. Verifies no breaking changes
4. Generates deployment report
"""
import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class DeploymentValidator:
    """Validates deployment readiness."""
    
    def __init__(self):
        self.results: List[Tuple[str, bool, str]] = []
        self.start_time = time.time()
    
    def log(self, component: str, passed: bool, message: str):
        """Log validation result."""
        self.results.append((component, passed, message))
        status = "✓" if passed else "✗"
        print(f"  [{status}] {component}: {message}")
    
    # ========================================================================
    # PHASE 1: Harden Mode Validation
    # ========================================================================
    
    def validate_privacy_audit(self) -> bool:
        """Validate privacy audit middleware."""
        try:
            from weebot.templates.privacy_audit import (
                PrivacyAuditMiddleware, PrivacyViolationType
            )
            
            audit = PrivacyAuditMiddleware(min_user_count=3)
            
            # Test blocking
            result = audit.allow_collaborative_query(
                template_name="test",
                user_id="user123",
                proposed_user_count=2,
            )
            assert result is False, "Should block low user count"
            
            # Test compliance tracking
            report = audit.get_report()
            assert report.violations >= 1, "Should track violations"
            
            self.log("Privacy Audit", True, f"Compliance tracking active (score: {report.compliance_score:.0%})")
            return True
            
        except Exception as e:
            self.log("Privacy Audit", False, str(e))
            return False
    
    def validate_rate_limiter_bounds(self) -> bool:
        """Validate rate limiter memory bounds."""
        try:
            from weebot.templates.production import RateLimiter, RateLimitConfig
            
            limiter = RateLimiter(
                backend="memory",
                config=RateLimitConfig(burst_size=10)
            )
            
            # Verify bounds exist
            assert hasattr(limiter, 'MAX_BUCKETS'), "Missing MAX_BUCKETS"
            assert hasattr(limiter, 'BUCKET_TTL_SECONDS'), "Missing BUCKET_TTL"
            assert hasattr(limiter, '_evict_lru_buckets'), "Missing LRU eviction"
            
            # Test metrics
            metrics = limiter.get_metrics()
            assert 'active_buckets' in metrics, "Missing metrics"
            
            self.log("Rate Limiter Bounds", True, f"Max buckets: {limiter.MAX_BUCKETS}")
            return True
            
        except Exception as e:
            self.log("Rate Limiter Bounds", False, str(e))
            return False
    
    def validate_yaml_security(self) -> bool:
        """Validate YAML security limits."""
        try:
            from weebot.templates.parser import (
                TemplateParser, TemplateSecurityError, SecureYamlLoader
            )
            
            parser = TemplateParser()
            
            # Verify security limits exist
            assert hasattr(SecureYamlLoader, 'MAX_DEPTH'), "Missing MAX_DEPTH"
            assert hasattr(SecureYamlLoader, 'MAX_NODES'), "Missing MAX_NODES"
            
            # Test rejection of oversized content
            huge_content = "x: " + "A" * (parser.MAX_TEMPLATE_SIZE + 100)
            try:
                parser.parse(huge_content)
                self.log("YAML Security", False, "Failed to reject oversized content")
                return False
            except TemplateSecurityError:
                pass  # Expected
            
            self.log("YAML Security", True, 
                    f"Limits: depth={SecureYamlLoader.MAX_DEPTH}, "
                    f"nodes={SecureYamlLoader.MAX_NODES}")
            return True
            
        except Exception as e:
            self.log("YAML Security", False, str(e))
            return False
    
    def validate_circuit_breaker_jitter(self) -> bool:
        """Validate circuit breaker jitter."""
        try:
            from weebot.core.circuit_breaker import CircuitBreaker
            
            breaker = CircuitBreaker(
                cooldown_seconds=60.0,
                jitter_percent=0.2,
            )
            
            # Verify jitter exists
            assert hasattr(breaker, '_get_jittered_cooldown'), "Missing jitter method"
            assert hasattr(breaker, '_maybe_stagger_probe'), "Missing stagger method"
            
            # Test jitter variation
            cooldowns = [breaker._get_jittered_cooldown() for _ in range(10)]
            unique = len(set(round(c, 1) for c in cooldowns))
            assert unique > 1, "Jitter not providing variation"
            
            # Test metrics
            metrics = breaker.get_metrics()
            assert 'recovery_rate' in metrics, "Missing recovery metrics"
            
            self.log("Circuit Breaker Jitter", True, 
                    f"Jitter: {breaker._jitter_percent:.0%}, "
                    f"Variation: {unique} values")
            return True
            
        except Exception as e:
            self.log("Circuit Breaker Jitter", False, str(e))
            return False
    
    def validate_db_pool_monitor(self) -> bool:
        """Validate DB pool monitoring."""
        try:
            from weebot.templates.db_monitor import ConnectionPoolMonitor
            
            monitor = ConnectionPoolMonitor(pool_size=10, max_overflow=0)
            
            # Test snapshot recording
            snapshot = monitor.record_pool_snapshot(
                checked_out=8, available=2, waiting=1
            )
            
            # Verify metrics
            metrics = monitor.get_metrics()
            assert 'saturation_alerts' in metrics, "Missing saturation tracking"
            
            self.log("DB Pool Monitor", True, 
                    f"Capacity: {metrics['pool_capacity']}, "
                    f"Alerts: {metrics['saturation_alerts']}")
            return True
            
        except Exception as e:
            self.log("DB Pool Monitor", False, str(e))
            return False
    
    # ========================================================================
    # PHASE 2: Regression Tests
    # ========================================================================
    
    def test_existing_circuit_breaker(self) -> bool:
        """Verify existing circuit breaker functionality."""
        try:
            from weebot.core.circuit_breaker import CircuitBreaker, BreakerState
            
            breaker = CircuitBreaker(
                failure_threshold=2,
                cooldown_seconds=0.1,  # Fast for testing
            )
            
            # Normal operation
            result = asyncio.run(breaker.evaluate("test_entity"))
            assert result.allowed is True, "Should allow normal requests"
            assert result.state == BreakerState.CLOSED, "Should start closed"
            
            # Failures trigger open
            asyncio.run(breaker.record_failure("test_entity"))
            asyncio.run(breaker.record_failure("test_entity"))
            
            result = asyncio.run(breaker.evaluate("test_entity"))
            assert result.state == BreakerState.OPEN, "Should be open after failures"
            
            self.log("CB Regression", True, "State machine working")
            return True
            
        except Exception as e:
            self.log("CB Regression", False, str(e))
            return False
    
    def test_existing_template_parser(self) -> bool:
        """Verify existing template parser functionality."""
        try:
            from weebot.templates.parser import TemplateParser
            
            parser = TemplateParser()
            
            valid_yaml = """
name: test_template
version: "1.0.0"
parameters:
  topic:
    type: string
    description: Topic to research
workflow:
  step1:
    type: agent_task
    prompt: "Research {{topic}}"
"""
            
            template = parser.parse(valid_yaml)
            assert template.name == "test_template", "Should parse name"
            assert "topic" in template.parameters, "Should parse parameters"
            assert "step1" in template.workflow, "Should parse workflow"
            
            self.log("Parser Regression", True, "Template parsing working")
            return True
            
        except Exception as e:
            self.log("Parser Regression", False, str(e))
            return False
    
    def test_existing_rate_limiter(self) -> bool:
        """Verify existing rate limiter functionality."""
        try:
            from weebot.templates.production import RateLimiter, RateLimitConfig
            
            limiter = RateLimiter(
                backend="memory",
                config=RateLimitConfig(burst_size=5)
            )
            
            # Should allow requests within burst
            results = [limiter.is_allowed("user1") for _ in range(5)]
            assert all(results), "Should allow burst requests"
            
            # Should rate limit after burst
            assert not limiter.is_allowed("user1"), "Should rate limit after burst"
            
            self.log("Rate Limiter Regression", True, "Token bucket working")
            return True
            
        except Exception as e:
            self.log("Rate Limiter Regression", False, str(e))
            return False
    
    def test_existing_workflow_orchestrator(self) -> bool:
        """Verify existing workflow orchestrator functionality."""
        try:
            from weebot.core.workflow_orchestrator import WorkflowOrchestrator
            
            orchestrator = WorkflowOrchestrator(
                max_parallel_agents=2,
                timeout_per_task=1.0,
            )
            
            # Verify properties exist
            assert orchestrator.max_parallel_agents == 2, "Should set parallel limit"
            assert orchestrator.timeout_per_task == 1.0, "Should set timeout"
            
            self.log("Orchestrator Regression", True, "Configuration working")
            return True
            
        except Exception as e:
            self.log("Orchestrator Regression", False, str(e))
            return False
    
    # ========================================================================
    # PHASE 3: Integration Tests
    # ========================================================================
    
    def test_production_engine_integration(self) -> bool:
        """Verify ProductionTemplateEngine integrates with hardening."""
        try:
            from weebot.templates.production import ProductionTemplateEngine
            
            # Create engine (without DB for testing)
            engine = ProductionTemplateEngine(
                database_url=None,  # Skip DB for unit test
                redis_url=None,
                rate_limit_backend="memory",
                enable_adaptive=False,
            )
            
            # Verify rate limiter has hardening
            assert hasattr(engine.rate_limiter, 'MAX_BUCKETS'), "Rate limiter not hardened"
            
            # Verify metrics available
            metrics = engine.rate_limiter.get_metrics()
            assert 'utilization' in metrics, "Metrics not available"
            
            self.log("Production Engine Integration", True, "Hardening integrated")
            return True
            
        except Exception as e:
            self.log("Production Engine Integration", False, str(e))
            return False
    
    # ========================================================================
    # MAIN
    # ========================================================================
    
    def run_all(self) -> Dict[str, any]:
        """Run all validation tests."""
        print("=" * 70)
        print("HARDEN MODE STAGING DEPLOYMENT VALIDATION")
        print("=" * 70)
        print(f"Timestamp: {datetime.now().isoformat()}")
        print(f"Project Root: {project_root}")
        print("=" * 70)
        
        # Phase 1: Harden Mode Validation
        print("\n[PHASE 1] HARDEN Mode Implementation Validation")
        print("-" * 70)
        harden_tests = [
            ("Privacy Audit", self.validate_privacy_audit),
            ("Rate Limiter Bounds", self.validate_rate_limiter_bounds),
            ("YAML Security", self.validate_yaml_security),
            ("Circuit Breaker Jitter", self.validate_circuit_breaker_jitter),
            ("DB Pool Monitor", self.validate_db_pool_monitor),
        ]
        
        harden_passed = sum(1 for name, test in harden_tests if test())
        
        # Phase 2: Regression Tests
        print("\n[PHASE 2] Regression Testing")
        print("-" * 70)
        regression_tests = [
            ("Circuit Breaker", self.test_existing_circuit_breaker),
            ("Template Parser", self.test_existing_template_parser),
            ("Rate Limiter", self.test_existing_rate_limiter),
            ("Workflow Orchestrator", self.test_existing_workflow_orchestrator),
        ]
        
        regression_passed = sum(1 for name, test in regression_tests if test())
        
        # Phase 3: Integration Tests
        print("\n[PHASE 3] Integration Testing")
        print("-" * 70)
        integration_tests = [
            ("Production Engine", self.test_production_engine_integration),
        ]
        
        integration_passed = sum(1 for name, test in integration_tests if test())
        
        # Summary
        total_tests = len(harden_tests) + len(regression_tests) + len(integration_tests)
        total_passed = harden_passed + regression_passed + integration_passed
        total_failed = total_tests - total_passed
        
        elapsed = time.time() - self.start_time
        
        print("\n" + "=" * 70)
        print("DEPLOYMENT VALIDATION SUMMARY")
        print("=" * 70)
        print(f"Harden Mode Tests:    {harden_passed}/{len(harden_tests)} passed")
        print(f"Regression Tests:     {regression_passed}/{len(regression_tests)} passed")
        print(f"Integration Tests:    {integration_passed}/{len(integration_tests)} passed")
        print("-" * 70)
        print(f"TOTAL: {total_passed}/{total_tests} passed, {total_failed} failed")
        print(f"Elapsed: {elapsed:.2f}s")
        print("=" * 70)
        
        # Deployment decision
        if total_failed == 0:
            print("\n✓ ALL TESTS PASSED - READY FOR STAGING DEPLOYMENT")
            return {
                "status": "PASSED",
                "passed": total_passed,
                "failed": total_failed,
                "elapsed_seconds": elapsed,
            }
        else:
            print(f"\n✗ {total_failed} TEST(S) FAILED - BLOCKING DEPLOYMENT")
            return {
                "status": "FAILED",
                "passed": total_passed,
                "failed": total_failed,
                "elapsed_seconds": elapsed,
            }


def main():
    """Main entry point."""
    validator = DeploymentValidator()
    result = validator.run_all()
    
    # Exit with appropriate code
    sys.exit(0 if result["status"] == "PASSED" else 1)


if __name__ == "__main__":
    main()
