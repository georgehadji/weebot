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


class TestInvalidRegexHandling:
    """Black swan fix: invalid regex in a user-supplied rule must not crash evaluate().

    Before the fix, re.search(bad_pattern, ...) would raise re.error at
    runtime, propagating through BashTool.execute() and killing the agent.
    """

    def test_invalid_regex_does_not_raise_on_evaluate(self):
        """A rule with an invalid regex pattern must be silently skipped."""
        policy = ExecApprovalPolicy(rules=[
            CommandRule(pattern="[unclosed", mode=ApprovalMode.DENY, is_regex=True),
        ])
        # Must not raise — the invalid rule is skipped, falls through to auto-approve
        result = policy.evaluate("any command here")
        assert result.approved is True
        assert result.requires_confirmation is False

    def test_invalid_regex_does_not_block_valid_literal_rules(self):
        """An invalid regex rule must not prevent valid literal rules from matching."""
        policy = ExecApprovalPolicy(rules=[
            CommandRule(pattern="(dangling", mode=ApprovalMode.DENY, is_regex=True),
            CommandRule(pattern="format", mode=ApprovalMode.DENY),
        ])
        result = policy.evaluate("format C:")
        assert result.approved is False

    def test_valid_regex_still_fires_alongside_invalid(self):
        """A valid regex rule must still match correctly when mixed with invalid ones."""
        policy = ExecApprovalPolicy(rules=[
            CommandRule(pattern="[bad", mode=ApprovalMode.DENY, is_regex=True),
            CommandRule(pattern=r"rm\s+-rf", mode=ApprovalMode.DENY, is_regex=True),
        ])
        result = policy.evaluate("rm -rf /important")
        assert result.approved is False

    def test_multiple_invalid_regexes_all_skipped(self):
        """Multiple invalid patterns must not cause cumulative failures."""
        policy = ExecApprovalPolicy(rules=[
            CommandRule(pattern="[a", mode=ApprovalMode.DENY, is_regex=True),
            CommandRule(pattern="(b", mode=ApprovalMode.DENY, is_regex=True),
            CommandRule(pattern="*c", mode=ApprovalMode.DENY, is_regex=True),
        ])
        # All three custom rules are invalid and skipped; built-in defaults still apply.
        result = policy.evaluate("ls -la")
        assert result.approved is True
