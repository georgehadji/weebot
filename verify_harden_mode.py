#!/usr/bin/env python3
"""Verify HARDEN mode implementations.

Run this script to verify all 5 hardening measures are working.
"""
import asyncio
import sys
from datetime import datetime


def test_privacy_audit():
    """Test 1: Privacy Audit Middleware"""
    print("\n[1/5] Testing Privacy Audit Middleware...")
    
    from weebot.templates.privacy_audit import PrivacyAuditMiddleware
    
    audit = PrivacyAuditMiddleware(min_user_count=3)
    
    # Test blocking
    result = audit.allow_collaborative_query(
        template_name="test_template",
        user_id="user123",
        proposed_user_count=2,  # Below minimum
    )
    assert result is False, "Should block low user count"
    
    # Test allowing
    result = audit.allow_collaborative_query(
        template_name="test_template",
        user_id="user456",
        proposed_user_count=5,  # Above minimum
    )
    assert result is True, "Should allow sufficient user count"
    
    # Check report
    report = audit.get_report()
    assert report.violations == 1, "Should have 1 violation"
    assert report.blocked_operations == 1, "Should have 1 blocked"
    
    print(f"  ✓ Privacy audit working (compliance: {report.compliance_score:.0%})")
    return True


def test_rate_limiter_bounds():
    """Test 2: Rate Limiter Bounds"""
    print("\n[2/5] Testing Rate Limiter Bounds...")
    
    from weebot.templates.production import RateLimiter, RateLimitConfig
    
    limiter = RateLimiter(
        backend="memory",
        config=RateLimitConfig(burst_size=10)
    )
    
    # Override for testing
    limiter.MAX_BUCKETS = 50
    
    # Create many buckets
    for i in range(75):
        limiter.is_allowed(f"user_{i}", "test")
    
    metrics = limiter.get_metrics()
    assert metrics["active_buckets"] <= 50, "Should enforce max buckets"
    
    print(f"  ✓ Rate limiter bounds working (evicted: {metrics['eviction_count']})")
    return True


def test_yaml_security():
    """Test 3: YAML Security Limits"""
    print("\n[3/5] Testing YAML Security Limits...")
    
    from weebot.templates.parser import TemplateParser, TemplateSecurityError
    
    parser = TemplateParser()
    
    # Test valid template
    valid_yaml = """
name: test_template
version: "1.0.0"
parameters:
  topic:
    type: string
workflow:
  step1:
    type: agent_task
"""
    template = parser.parse(valid_yaml)
    assert template.name == "test_template"
    
    # Test oversized document
    huge_content = "x: " + "A" * (parser.MAX_TEMPLATE_SIZE + 100)
    try:
        parser.parse(huge_content)
        assert False, "Should reject oversized document"
    except TemplateSecurityError as e:
        assert "size" in str(e).lower()
    
    # Test too many parameters
    params = "\n".join([f"  param_{i}:\n    type: string" for i in range(60)])
    yaml_with_many_params = f"""
name: test
parameters:
{params}
workflow:
  step1:
    type: agent_task
"""
    try:
        parser.parse(yaml_with_many_params)
        assert False, "Should reject too many parameters"
    except TemplateSecurityError as e:
        assert "parameters" in str(e).lower()
    
    print("  ✓ YAML security limits working")
    return True


def test_circuit_breaker_jitter():
    """Test 4: Circuit Breaker Jitter"""
    print("\n[4/5] Testing Circuit Breaker Jitter...")
    
    from weebot.core.circuit_breaker import CircuitBreaker
    
    breaker = CircuitBreaker(
        cooldown_seconds=60.0,
        jitter_percent=0.2,
    )
    
    # Test jitter variation
    cooldowns = [breaker._get_jittered_cooldown() for _ in range(50)]
    base = 60.0
    jitter = base * 0.2
    
    for cd in cooldowns:
        assert base - jitter <= cd <= base + jitter, "Cooldown out of jitter range"
    
    # Verify variation exists
    unique = len(set(round(c, 1) for c in cooldowns))
    assert unique > 1, "Should have variation"
    
    # Test metrics
    metrics = breaker.get_metrics()
    assert "jitter_enabled" in metrics
    assert metrics["jitter_percent"] == 0.2
    
    print(f"  ✓ Circuit breaker jitter working ({unique} unique values)")
    return True


def test_db_pool_monitor():
    """Test 5: DB Pool Monitor"""
    print("\n[5/5] Testing DB Pool Monitor...")
    
    from weebot.templates.db_monitor import ConnectionPoolMonitor
    
    # pool_size=10, max_overflow=10 (default), so total_capacity=20
    monitor = ConnectionPoolMonitor(pool_size=10, max_overflow=0)  # No overflow for testing
    
    # Test snapshot recording
    monitor.record_pool_snapshot(checked_out=8, available=2, waiting=1)
    
    metrics = monitor.get_metrics()
    assert metrics["pool_capacity"] == 10, f"Expected 10, got {metrics['pool_capacity']}"
    
    # Test saturation alert (9/10 = 90%, threshold is 80%)
    monitor.record_pool_snapshot(checked_out=9, available=1, waiting=2)
    
    metrics = monitor.get_metrics()
    assert metrics["saturation_alerts"] == 1, f"Expected 1 alert, got {metrics['saturation_alerts']}"
    
    print(f"  ✓ DB pool monitor working (alerts: {metrics['saturation_alerts']})")
    return True


def main():
    """Run all HARDEN mode verification tests."""
    print("=" * 60)
    print("HARDEN MODE VERIFICATION")
    print("=" * 60)
    
    tests = [
        ("Privacy Audit Middleware", test_privacy_audit),
        ("Rate Limiter Bounds", test_rate_limiter_bounds),
        ("YAML Security Limits", test_yaml_security),
        ("Circuit Breaker Jitter", test_circuit_breaker_jitter),
        ("DB Pool Monitor", test_db_pool_monitor),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            failed += 1
            print(f"  ✗ {name} FAILED: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed == 0:
        print("\n✓ All HARDEN mode measures verified successfully!")
        return 0
    else:
        print(f"\n✗ {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
