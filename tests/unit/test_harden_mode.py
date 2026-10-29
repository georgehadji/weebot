"""Tests for HARDEN mode security features.

Verifies the hardening measures that remain:
1. YAML Security Limits
2. Circuit Breaker Jitter
"""

import asyncio
import pytest


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

        breaker = CircuitBreaker(cooldown_seconds=60.0, jitter_percent=0.2)

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
            failure_threshold=1, cooldown_seconds=0.1, success_threshold=1  # Fast for testing
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
