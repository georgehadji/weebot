"""Unit tests for ExecApprovalPolicy."""
import pytest
from weebot.core.approval_policy import ExecApprovalPolicy, ApprovalMode, CommandRule


class TestDefaultPolicy:
    def setup_method(self):
        self.policy = ExecApprovalPolicy()

    def test_non_critical_command_auto_approved(self):
        result = self.policy.evaluate("Get-ChildItem C:\\")
        assert result.approved is True
        assert result.requires_confirmation is False

    def test_delete_command_requires_confirmation_by_default(self):
        result = self.policy.evaluate("Remove-Item old_logs")
        assert result.requires_confirmation is True

    def test_format_command_denied_by_default(self):
        result = self.policy.evaluate("Format-Volume C")
        assert result.approved is False

    def test_result_has_undo_hint(self):
        result = self.policy.evaluate("Remove-Item log.txt")
        assert isinstance(result.undo_hint, str)


class TestCustomRules:
    def test_whitelist_rule_auto_approves(self):
        policy = ExecApprovalPolicy(rules=[
            CommandRule(pattern="Get-Process", mode=ApprovalMode.AUTO_APPROVE),
        ])
        result = policy.evaluate("Get-Process chrome")
        assert result.approved is True
        assert result.requires_confirmation is False

    def test_deny_rule_blocks_command(self):
        policy = ExecApprovalPolicy(rules=[
            CommandRule(pattern="curl", mode=ApprovalMode.DENY),
        ])
        result = policy.evaluate("curl http://example.com")
        assert result.approved is False

    def test_ask_rule_requires_confirmation(self):
        policy = ExecApprovalPolicy(rules=[
            CommandRule(pattern="npm install", mode=ApprovalMode.ALWAYS_ASK),
        ])
        result = policy.evaluate("npm install --save-dev")
        assert result.requires_confirmation is True

    def test_most_specific_rule_wins(self):
        policy = ExecApprovalPolicy(rules=[
            CommandRule(pattern="Remove-Item", mode=ApprovalMode.ALWAYS_ASK),
            CommandRule(pattern="Remove-Item C:\\Windows", mode=ApprovalMode.DENY),
        ])
        result = policy.evaluate("Remove-Item C:\\Windows\\system32")
        assert result.approved is False


class TestApprovalResult:
    def test_result_contains_command(self):
        policy = ExecApprovalPolicy()
        result = policy.evaluate("Get-ChildItem")
        assert result.command == "Get-ChildItem"
